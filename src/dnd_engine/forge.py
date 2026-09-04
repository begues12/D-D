"""La fragua de aventuras: el modelo propone historias y las monta como planos.

El menu ya no esta atado a los cuatro escenarios escritos a mano. La fragua hace
dos cosas separadas a proposito:

1. **Proponer** (`propose`) - varios ganchos de aventura, cortos y baratos, para
   que el grupo elija antes de gastar nada en construir el mundo.
2. **Montar** (`build`) - convierte el gancho elegido en un plano completo:
   ubicaciones con cuadricula, puertas, llaves, enemigos, botin y mision.

Lo que sale del modelo **no se juega sin revisar**. `validate_scenario` es la
aduana: comprueba que los identificadores existan, que las casillas caigan
dentro de la cuadricula y no en un muro, que dos criaturas no nazcan encima la
una de la otra, que la mision apunte a algo real y -lo mas importante- que la
aventura **se pueda terminar**: cada llave tiene que estar en una ubicacion a la
que se llegue antes de la puerta que abre. Si algo no cuadra, el error concreto
vuelve al modelo y se le pide que lo arregle.

El plano generado es exactamente el mismo `dict` que las entradas de
`SCENARIOS`, asi que `build_campaign` no distingue una aventura inventada de una
escrita a mano.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ai_dm import DungeonMasterError, ModelSession
from .dice import Dice
from .models import Condition, ItemEffect

# Cuantas veces se le devuelve el error de validacion al modelo antes de rendirse.
REPAIR_ATTEMPTS = 3
DEFAULT_PROPOSALS = 3
MAX_PROPOSALS = 6

MIN_LOCATIONS, MAX_LOCATIONS = 2, 5
MAX_GRID = 12
MAX_ENEMIES = 8

# Solo estos eventos existen de verdad en el motor. Un objetivo suscrito a
# cualquier otro no se completaria nunca, asi que la aventura seria injugable.
OBJECTIVE_EVENTS = {
    "PLAYER_ENTERED_LOCATION": "ubicacion",
    "NPC_DIES": "personaje",
    "ITEM_TAKEN": "objeto",
    "DOOR_UNLOCKED": "puerta",
}

ABILITIES = {"strength", "dexterity", "constitution",
             "intelligence", "wisdom", "charisma"}

# Los ids de los jugadores se construyen como "hero-<nombre>": reservados.
RESERVED_PREFIX = "hero-"


class ScenarioError(ValueError):
    """El plano no es jugable. El mensaje dice exactamente que falla."""


@dataclass(frozen=True)
class Pitch:
    """Un gancho de aventura: lo justo para elegir, sin construir nada."""

    id: str
    name: str
    description: str
    intro: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name,
                "description": self.description, "intro": self.intro}


# -- aduana -------------------------------------------------------------------


def validate_scenario(blueprint: Any) -> dict[str, Any]:
    """Comprueba que el plano sea jugable y lo devuelve. Si no, `ScenarioError`."""
    if not isinstance(blueprint, dict):
        raise ScenarioError("El escenario tiene que ser un objeto.")
    for key in ("name", "description", "start", "locations", "quest"):
        if not blueprint.get(key):
            raise ScenarioError(f"Falta '{key}' en el escenario.")

    locations = _validate_locations(blueprint["locations"])
    if blueprint["start"] not in locations:
        raise ScenarioError(
            f"'start' apunta a '{blueprint['start']}', que no es ninguna ubicacion.")

    items = _validate_items(locations)
    doors = _validate_doors(blueprint.get("doors", []), locations, items)
    characters = _validate_characters(blueprint, locations)
    _validate_quest(blueprint["quest"], locations, characters, items, doors)
    _validate_reachability(blueprint["start"], locations, doors, items)
    return blueprint


def _validate_locations(data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(data, list) or not data:
        raise ScenarioError("'locations' tiene que ser una lista de ubicaciones.")
    if not MIN_LOCATIONS <= len(data) <= MAX_LOCATIONS:
        raise ScenarioError(
            f"Hacen falta entre {MIN_LOCATIONS} y {MAX_LOCATIONS} ubicaciones, "
            f"no {len(data)}.")
    locations: dict[str, dict[str, Any]] = {}
    for one in data:
        identifier = _identifier(one, "ubicacion")
        if identifier in locations:
            raise ScenarioError(f"Hay dos ubicaciones con el id '{identifier}'.")
        if not one.get("name"):
            raise ScenarioError(f"La ubicacion '{identifier}' no tiene nombre.")
        _validate_grid(identifier, one.get("grid"))
        locations[identifier] = one
    return locations


def _validate_grid(location_id: str, grid: Any) -> None:
    if grid is None:
        return
    if not isinstance(grid, dict):
        raise ScenarioError(f"La cuadricula de '{location_id}' tiene que ser un objeto.")
    for side in ("width", "height"):
        size = grid.get(side)
        if not isinstance(size, int) or not 2 <= size <= MAX_GRID:
            raise ScenarioError(
                f"La cuadricula de '{location_id}' necesita '{side}' entre 2 y {MAX_GRID}.")
    blocked = grid.get("blocked", [])
    if not isinstance(blocked, list):
        raise ScenarioError(f"'blocked' de '{location_id}' tiene que ser una lista.")
    for cell in blocked:
        _cell_inside(cell, grid, f"una casilla bloqueada de '{location_id}'")
    if len(_cells(blocked)) >= grid["width"] * grid["height"] - 1:
        raise ScenarioError(f"'{location_id}' esta bloqueada casi entera.")


def _validate_items(locations: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Devuelve {id del objeto: ubicacion donde esta}."""
    items: dict[str, str] = {}
    for location_id, location in locations.items():
        grid = location.get("grid")
        occupied: set[tuple[int, int]] = set()
        for one in location.get("items", []):
            identifier = _identifier(one, "objeto")
            if identifier in items:
                raise ScenarioError(f"Hay dos objetos con el id '{identifier}'.")
            if not one.get("name"):
                raise ScenarioError(f"El objeto '{identifier}' no tiene nombre.")
            cell = one.get("cell")
            if cell is not None:
                if grid is None:
                    raise ScenarioError(
                        f"El objeto '{identifier}' tiene casilla, pero '{location_id}' "
                        "no tiene cuadricula.")
                position = _cell_inside(cell, grid, f"el objeto '{identifier}'")
                if position in _cells(grid.get("blocked", [])):
                    raise ScenarioError(
                        f"El objeto '{identifier}' esta dentro de un muro en '{location_id}'.")
                if position in occupied:
                    raise ScenarioError(
                        f"Dos objetos comparten la casilla {list(position)} en '{location_id}'.")
                occupied.add(position)
            _validate_consumable(identifier, one)
            items[identifier] = location_id
    return items


def _validate_consumable(identifier: str, data: dict[str, Any]) -> None:
    effect = data.get("effect")
    if effect is None:
        return
    try:
        effect = ItemEffect(effect)
    except ValueError:
        raise ScenarioError(
            f"El objeto '{identifier}' tiene un efecto desconocido: '{data['effect']}'. "
            f"Opciones: {', '.join(one.value for one in ItemEffect)}.") from None
    if effect is ItemEffect.HEAL:
        _dice(data.get("healing", "0"), f"la curacion de '{identifier}'")
    elif not data.get("condition"):
        raise ScenarioError(f"El objeto '{identifier}' cura, pero no dice que estado quita.")
    if data.get("condition"):
        _condition(data["condition"], f"el objeto '{identifier}'")
    uses = data.get("uses", 1)
    if not isinstance(uses, int) or uses < 1:
        raise ScenarioError(f"El objeto '{identifier}' necesita al menos un uso.")


def _validate_doors(data: Any, locations: dict[str, dict[str, Any]],
                    items: dict[str, str]) -> dict[str, dict[str, Any]]:
    if not isinstance(data, list):
        raise ScenarioError("'doors' tiene que ser una lista.")
    if len(locations) > 1 and not data:
        raise ScenarioError("Hay varias ubicaciones y ninguna puerta que las conecte.")
    doors: dict[str, dict[str, Any]] = {}
    for one in data:
        identifier = _identifier(one, "puerta")
        if identifier in doors:
            raise ScenarioError(f"Hay dos puertas con el id '{identifier}'.")
        for side in ("a", "b"):
            if one.get(side) not in locations:
                raise ScenarioError(
                    f"La puerta '{identifier}' da a '{one.get(side)}', que no existe.")
        if one["a"] == one["b"]:
            raise ScenarioError(f"La puerta '{identifier}' une '{one['a']}' consigo misma.")
        for side, cell_key in (("a", "cell_a"), ("b", "cell_b")):
            cell = one.get(cell_key)
            if cell is None:
                continue
            grid = locations[one[side]].get("grid")
            if grid is None:
                raise ScenarioError(
                    f"La puerta '{identifier}' tiene '{cell_key}', pero '{one[side]}' "
                    "no tiene cuadricula.")
            position = _cell_inside(cell, grid, f"'{cell_key}' de la puerta '{identifier}'")
            if position in _cells(grid.get("blocked", [])):
                raise ScenarioError(
                    f"La puerta '{identifier}' esta dentro de un muro en '{one[side]}'.")
        if one.get("locked"):
            key = one.get("key_id")
            if not key:
                raise ScenarioError(f"La puerta '{identifier}' esta cerrada y no tiene llave.")
            if key not in items:
                raise ScenarioError(
                    f"La llave '{key}' de la puerta '{identifier}' no esta en ninguna parte.")
        doors[identifier] = one
    return doors


def _validate_characters(blueprint: dict[str, Any],
                         locations: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Devuelve {id del personaje: ubicacion}. Comprueba tambien las casillas."""
    characters: dict[str, str] = {}
    taken: dict[str, set[tuple[int, int]]] = {one: set() for one in locations}

    enemies = blueprint.get("enemies", [])
    if not isinstance(enemies, list) or len(enemies) > MAX_ENEMIES:
        raise ScenarioError(f"'enemies' tiene que ser una lista de {MAX_ENEMIES} como mucho.")
    for one in enemies:
        identifier = _place_character(one, "enemigo", locations, characters, taken)
        _validate_enemy(identifier, one)

    npcs = blueprint.get("npcs", [])
    if not isinstance(npcs, list):
        raise ScenarioError("'npcs' tiene que ser una lista.")
    for one in npcs:
        _place_character(one, "personaje", locations, characters, taken)
    return characters


def _place_character(data: Any, what: str, locations: dict[str, dict[str, Any]],
                     characters: dict[str, str],
                     taken: dict[str, set[tuple[int, int]]]) -> str:
    identifier = _identifier(data, what)
    if identifier in characters:
        raise ScenarioError(f"Hay dos personajes con el id '{identifier}'.")
    if identifier.startswith(RESERVED_PREFIX):
        raise ScenarioError(
            f"El id '{identifier}' empieza por '{RESERVED_PREFIX}', reservado a los jugadores.")
    if not data.get("name"):
        raise ScenarioError(f"El {what} '{identifier}' no tiene nombre.")
    location_id = data.get("location")
    if location_id not in locations:
        raise ScenarioError(
            f"El {what} '{identifier}' esta en '{location_id}', que no existe.")
    cell = data.get("cell")
    grid = locations[location_id].get("grid")
    if cell is not None:
        if grid is None:
            raise ScenarioError(
                f"El {what} '{identifier}' tiene casilla, pero '{location_id}' "
                "no tiene cuadricula.")
        position = _cell_inside(cell, grid, f"el {what} '{identifier}'")
        if position in _cells(grid.get("blocked", [])):
            raise ScenarioError(
                f"El {what} '{identifier}' esta dentro de un muro en '{location_id}'.")
        if position in taken[location_id]:
            raise ScenarioError(
                f"'{identifier}' nace encima de otro personaje en {list(position)}.")
        taken[location_id].add(position)
    # Sin casilla el motor le busca un hueco libre al colocarlo: es valido.
    characters[identifier] = location_id
    return identifier


def _validate_enemy(identifier: str, data: dict[str, Any]) -> None:
    max_hp = data.get("max_hp")
    if not isinstance(max_hp, int) or not 1 <= max_hp <= 200:
        raise ScenarioError(f"El enemigo '{identifier}' necesita 'max_hp' entre 1 y 200.")
    armor = data.get("armor_class")
    if not isinstance(armor, int) or not 5 <= armor <= 25:
        raise ScenarioError(f"El enemigo '{identifier}' necesita 'armor_class' entre 5 y 25.")
    xp = data.get("xp", 0)
    if not isinstance(xp, int) or xp < 0:
        raise ScenarioError(f"La experiencia de '{identifier}' no puede ser negativa.")
    for ability, score in (data.get("abilities") or {}).items():
        if ability not in ABILITIES:
            raise ScenarioError(
                f"'{identifier}' tiene una caracteristica desconocida: '{ability}'. "
                f"Opciones: {', '.join(sorted(ABILITIES))}.")
        if not isinstance(score, int) or not 1 <= score <= 30:
            raise ScenarioError(f"La caracteristica '{ability}' de '{identifier}' es imposible.")
    weapon = data.get("weapon")
    if not isinstance(weapon, dict) or not weapon.get("name"):
        raise ScenarioError(f"El enemigo '{identifier}' necesita un arma con nombre.")
    _dice(weapon.get("damage", "1d6"), f"el arma de '{identifier}'")
    for key in ("attack_bonus", "reach"):
        if key in weapon and not isinstance(weapon[key], int):
            raise ScenarioError(f"'{key}' del arma de '{identifier}' tiene que ser un numero.")


def _validate_quest(quest: Any, locations: dict[str, dict[str, Any]],
                    characters: dict[str, str], items: dict[str, str],
                    doors: dict[str, dict[str, Any]]) -> None:
    if not isinstance(quest, dict):
        raise ScenarioError("'quest' tiene que ser un objeto.")
    _identifier(quest, "mision")
    if not quest.get("name"):
        raise ScenarioError("La mision no tiene nombre.")
    objectives = quest.get("objectives")
    if not isinstance(objectives, list) or not objectives:
        raise ScenarioError("La mision necesita al menos un objetivo.")
    universe = {"ubicacion": locations, "personaje": characters,
                "objeto": items, "puerta": doors}
    seen: set[str] = set()
    for one in objectives:
        identifier = _identifier(one, "objetivo")
        if identifier in seen:
            raise ScenarioError(f"Hay dos objetivos con el id '{identifier}'.")
        seen.add(identifier)
        if not one.get("description"):
            raise ScenarioError(f"El objetivo '{identifier}' no dice que hay que hacer.")
        event = one.get("event_type")
        if event not in OBJECTIVE_EVENTS:
            raise ScenarioError(
                f"El objetivo '{identifier}' escucha '{event}', que el motor no publica. "
                f"Opciones: {', '.join(sorted(OBJECTIVE_EVENTS))}.")
        target = one.get("target_id")
        kind = OBJECTIVE_EVENTS[event]
        if target is not None and target not in universe[kind]:
            raise ScenarioError(
                f"El objetivo '{identifier}' apunta a '{target}', que no es "
                f"ninguna {kind} del escenario.")


def _validate_reachability(start: str, locations: dict[str, dict[str, Any]],
                           doors: dict[str, dict[str, Any]],
                           items: dict[str, str]) -> None:
    """Una aventura donde la llave esta detras de su propia puerta no se termina.

    Se avanza por punto fijo: se abre lo que permiten las llaves ya alcanzables,
    eso abre ubicaciones nuevas, que dan llaves nuevas.
    """
    reached = {start}
    growing = True
    while growing:
        growing = False
        keys = {item for item, where in items.items() if where in reached}
        for door in doors.values():
            if door.get("locked") and door.get("key_id") not in keys:
                continue
            for side, other in (("a", "b"), ("b", "a")):
                if door[side] in reached and door[other] not in reached:
                    reached.add(door[other])
                    growing = True
    unreachable = sorted(set(locations) - reached)
    if unreachable:
        raise ScenarioError(
            "No se puede llegar a " + ", ".join(f"'{one}'" for one in unreachable)
            + f" desde '{start}': o no hay puerta, o la llave esta al otro lado. "
            "Pon cada llave en una ubicacion anterior a la puerta que abre.")


# -- utilidades de validacion -------------------------------------------------


def _identifier(data: Any, what: str) -> str:
    if not isinstance(data, dict):
        raise ScenarioError(f"Cada {what} tiene que ser un objeto.")
    identifier = data.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ScenarioError(f"Hay una {what} sin 'id'.")
    if not all(letter.isalnum() or letter in "-_" for letter in identifier):
        raise ScenarioError(
            f"El id '{identifier}' solo puede llevar letras, numeros, guiones y '_'.")
    return identifier


def _cell_inside(cell: Any, grid: dict[str, Any], what: str) -> tuple[int, int]:
    if (not isinstance(cell, (list, tuple)) or len(cell) != 2
            or not all(isinstance(one, int) for one in cell)):
        raise ScenarioError(f"La casilla de {what} tiene que ser [x, y].")
    x, y = cell
    if not (0 <= x < grid["width"] and 0 <= y < grid["height"]):
        raise ScenarioError(
            f"La casilla de {what} es {list(cell)}, fuera de la cuadricula "
            f"{grid['width']}x{grid['height']} (las coordenadas empiezan en 0).")
    return (x, y)


def _cells(values: Any) -> set[tuple[int, int]]:
    return {tuple(one) for one in values if isinstance(one, (list, tuple)) and len(one) == 2}


def _dice(notation: Any, what: str) -> None:
    try:
        Dice.parse(notation)
    except ValueError as error:
        raise ScenarioError(f"La tirada de {what} no vale: {error}") from None


def _condition(value: Any, what: str) -> None:
    try:
        Condition(value)
    except ValueError:
        raise ScenarioError(
            f"El estado '{value}' de {what} no existe. "
            f"Opciones: {', '.join(one.value for one in Condition)}.") from None


# -- lo que se le pide al modelo ----------------------------------------------


PROPOSE_SYSTEM = """\
Eres el maestro de ceremonias de una partida de D&D. Propones ideas de aventura \
cortas para que el grupo elija una.

Cada propuesta es un gancho, no un guion: un lugar concreto, algo que va mal y \
un motivo para entrar. Cada una tiene que ser claramente distinta de las otras \
en lugar, tono y clase de amenaza; nada de tres variantes de la misma cueva.

Escribe en espanol, sin tildes ni caracteres especiales (el juego corre en una \
consola). La descripcion es una frase. La introduccion son tres o cuatro frases \
concretas, con detalles fisicos, sin promesas de lo que ocurrira.

La aventura se va a jugar en un motor pequeno: tres o cuatro salas, un punado de \
enemigos y una mision. No propongas nada que necesite ciudades, ejercitos, \
viajes largos ni magia que el motor no tiene.
"""

BUILD_SYSTEM = """\
Eres el disenador de mazmorras de un motor de D&D. Conviertes un gancho de \
aventura en un plano jugable, y solo en eso: no narras.

FORMATO
- Entre 2 y 5 ubicaciones. Cada una con id, nombre y descripcion.
- La cuadricula es opcional pero recomendable en las salas donde habra combate: \
  width y height entre 4 y 10, y 'blocked' con las casillas de muro o mobiliario \
  (pocas, nunca un pasillo cerrado).
- Las coordenadas son [x, y] y **empiezan en 0**: en una cuadricula 6x4 la \
  esquina opuesta es [5, 3].
- Dos personajes no pueden nacer en la misma casilla, ni encima de un muro.
- Las puertas conectan dos ubicaciones distintas y pueden tener cell_a y cell_b, \
  la casilla que ocupan a cada lado.

QUE HACE JUGABLE UNA AVENTURA
- Todo se recorre desde 'start'. Si una puerta esta cerrada con llave, la llave \
  tiene que estar en una ubicacion a la que se llegue **antes** de esa puerta. \
  Una llave detras de su propia puerta hace la aventura imposible.
- Entre 2 y 5 enemigos repartidos, no todos en la misma sala. Sube la amenaza \
  segun se avanza y deja al mas peligroso al final.
- Enemigos normales: 6-14 max_hp, armor_class 11-14, dano 1d6+1 o 1d8+1. \
  El jefe: 18-30 max_hp, armor_class 14-16, dano 1d10+3. La experiencia va de 25 \
  para un secuaz a 200 para un jefe.
- Pon algun consumible de curacion por el camino: effect 'heal' y healing en \
  notacion de dados ('1d8+2').
- La mision son uno o dos objetivos que el motor pueda ver ocurrir: \
  PLAYER_ENTERED_LOCATION con el id de una ubicacion, NPC_DIES con el id de un \
  enemigo, ITEM_TAKEN con el id de un objeto, DOOR_UNLOCKED con el id de una \
  puerta. Nada mas existe.
- Los ids son en minuscula, con guiones, y no empiezan por 'hero-'.

Escribe en espanol, sin tildes ni caracteres especiales.
"""

_CELL = {"type": "array", "items": {"type": "integer"},
         "minItems": 2, "maxItems": 2,
         "description": "Casilla [x, y], desde 0."}

PROPOSE_TOOL = {
    "name": "propose_adventures",
    "description": "Propone varias ideas de aventura para que el grupo elija.",
    "input_schema": {
        "type": "object",
        "properties": {
            "adventures": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Titulo de la aventura."},
                        "description": {"type": "string",
                                        "description": "Una frase: que pasa y donde."},
                        "intro": {"type": "string",
                                  "description": "Tres o cuatro frases de gancho."},
                    },
                    "required": ["name", "description", "intro"],
                },
            },
        },
        "required": ["adventures"],
    },
}

SCENARIO_TOOL = {
    "name": "build_adventure",
    "description": "Entrega el plano completo y jugable de una aventura.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string", "description": "Una frase."},
            "intro": {"type": "string", "description": "El gancho, tres o cuatro frases."},
            "start": {"type": "string", "description": "Id de la ubicacion donde empieza el grupo."},
            "locations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "grid": {
                            "type": "object",
                            "properties": {
                                "width": {"type": "integer"},
                                "height": {"type": "integer"},
                                "blocked": {"type": "array", "items": _CELL},
                            },
                            "required": ["width", "height"],
                        },
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                    "cell": _CELL,
                                    "effect": {"type": "string", "enum": ["heal", "cure"],
                                               "description": "Solo si es un consumible."},
                                    "healing": {"type": "string",
                                                "description": "Notacion de dados, '1d8+2'."},
                                    "condition": {"type": "string",
                                                  "description": "Estado que quita, si cura."},
                                    "uses": {"type": "integer"},
                                },
                                "required": ["id", "name"],
                            },
                        },
                    },
                    "required": ["id", "name", "description"],
                },
            },
            "doors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "a": {"type": "string"}, "b": {"type": "string"},
                        "cell_a": _CELL, "cell_b": _CELL,
                        "locked": {"type": "boolean"},
                        "key_id": {"type": "string",
                                   "description": "Id del objeto que la abre."},
                    },
                    "required": ["id", "a", "b"],
                },
            },
            "npcs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "location": {"type": "string"},
                        "cell": _CELL,
                        "personality": {"type": "array", "items": {"type": "string"}},
                        "knowledge": {"type": "array", "items": {"type": "string"}},
                        "goals": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "name", "location"],
                },
            },
            "enemies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "max_hp": {"type": "integer"},
                        "armor_class": {"type": "integer"},
                        "xp": {"type": "integer"},
                        "location": {"type": "string"},
                        "cell": _CELL,
                        "abilities": {
                            "type": "object",
                            "properties": {one: {"type": "integer"} for one in sorted(ABILITIES)},
                        },
                        "weapon": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "damage": {"type": "string",
                                           "description": "Notacion de dados, '1d8+2'."},
                                "attack_bonus": {"type": "integer"},
                                "reach": {"type": "integer",
                                          "description": "Alcance en pies; 5 cuerpo a cuerpo."},
                            },
                            "required": ["name", "damage", "attack_bonus"],
                        },
                    },
                    "required": ["id", "name", "max_hp", "armor_class", "location", "weapon"],
                },
            },
            "quest": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "objectives": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "description": {"type": "string"},
                                "event_type": {"type": "string",
                                               "enum": sorted(OBJECTIVE_EVENTS)},
                                "target_id": {"type": "string"},
                            },
                            "required": ["id", "description", "event_type", "target_id"],
                        },
                    },
                },
                "required": ["id", "name", "objectives"],
            },
        },
        "required": ["name", "description", "intro", "start", "locations", "doors",
                     "enemies", "quest"],
    },
}


class ScenarioForge(ModelSession):
    """Inventa aventuras y las deja en el mismo formato que las escritas a mano."""

    def propose(self, count: int = DEFAULT_PROPOSALS, hint: str = "",
                party_size: int = 1, avoid: tuple[str, ...] = ()) -> list[Pitch]:
        """Varios ganchos para elegir. No construye nada todavia."""
        count = max(1, min(count, MAX_PROPOSALS))
        request = [f"Propon exactamente {count} aventuras distintas.",
                   f"El grupo son {party_size} jugador(es) de nivel 1."]
        if hint:
            request.append(f"El grupo ha pedido: {hint}")
        if avoid:
            request.append("Ya has propuesto antes estas, no las repitas ni las "
                           "parafrasees: " + "; ".join(avoid))

        response = self._call(
            system=self._system(PROPOSE_SYSTEM),
            tools=[PROPOSE_TOOL],
            tool_choice={"type": "tool", "name": PROPOSE_TOOL["name"]},
            messages=[{"role": "user", "content": "\n".join(request)}],
        )
        adventures = _tool_input(response, PROPOSE_TOOL["name"]).get("adventures") or []
        pitches: list[Pitch] = []
        for one in adventures[:count]:
            name = (one.get("name") or "").strip()
            if not name:
                continue
            pitches.append(Pitch(
                _unique_slug(name, {pitch.id for pitch in pitches}), name,
                (one.get("description") or "").strip(), (one.get("intro") or "").strip()))
        if not pitches:
            raise DungeonMasterError("El modelo no propuso ninguna aventura.")
        return pitches

    def build(self, pitch: Pitch, hint: str = "", party_size: int = 1,
              attempts: int = REPAIR_ATTEMPTS) -> dict[str, Any]:
        """Monta el plano de la aventura elegida, y no lo devuelve hasta que sea jugable.

        Si la aduana lo rechaza, el motivo exacto vuelve al modelo como resultado
        de su propia herramienta: es la forma que tiene de arreglar su plano sin
        empezar de cero.
        """
        request = [
            f"Monta esta aventura para {party_size} jugador(es) de nivel 1.",
            f"Titulo: {pitch.name}",
            f"Idea: {pitch.description}",
        ]
        if pitch.intro:
            request.append(f"Gancho: {pitch.intro}")
        if hint:
            request.append(f"El grupo ha pedido ademas: {hint}")
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "\n".join(request)}]

        last: ScenarioError | None = None
        for _ in range(max(1, attempts)):
            reply = self._call(
                system=self._system(BUILD_SYSTEM),
                tools=[SCENARIO_TOOL],
                tool_choice={"type": "tool", "name": SCENARIO_TOOL["name"]},
                messages=messages,
            )
            block = _tool_block(reply, SCENARIO_TOOL["name"])
            blueprint = dict(block.input)
            blueprint.setdefault("intro", pitch.intro)
            try:
                return validate_scenario(blueprint)
            except ScenarioError as error:
                last = error
                messages = messages + [
                    # Su propio turno vuelve tal cual: la casa de IA sabe en que
                    # forma lo quiere de vuelta.
                    {"role": "assistant", "content": self.provider.assistant_echo(reply)},
                    {"role": "user", "content": [{
                        "type": "tool_result", "tool_use_id": block.id, "is_error": True,
                        "content": f"El plano no es jugable: {error} "
                                   "Corrige solo eso y vuelve a entregarlo entero.",
                    }]},
                ]
        raise DungeonMasterError(
            f"El modelo no consiguio un escenario jugable en {attempts} intentos. "
            f"Ultimo fallo: {last}")

    def forge(self, count: int = DEFAULT_PROPOSALS, hint: str = "",
              party_size: int = 1) -> list[tuple[Pitch, dict[str, Any]]]:
        """Propone y monta todas las aventuras de golpe.

        Cuesta una llamada por aventura, asi que el menu prefiere proponer
        primero y montar solo la elegida. Esta aqui para quien quiera verlas
        todas terminadas antes de decidir.
        """
        return [(pitch, self.build(pitch, hint, party_size))
                for pitch in self.propose(count, hint, party_size)]


def _tool_block(reply: Any, name: str):
    blocks = reply.tool_uses(name)
    if not blocks:
        raise DungeonMasterError(
            f"El modelo no uso la herramienta '{name}' "
            f"(stop_reason={reply.stop_reason}).")
    return blocks[0]


def _tool_input(reply: Any, name: str) -> dict[str, Any]:
    return dict(_tool_block(reply, name).input)


def _unique_slug(name: str, taken: set[str]) -> str:
    cleaned = "".join(
        letter if letter.isalnum() else "-" for letter in name.strip().lower())
    slug = "-".join(part for part in cleaned.split("-") if part)[:40] or "aventura"
    candidate, number = slug, 2
    while candidate in taken:
        candidate, number = f"{slug}-{number}", number + 1
    return candidate
