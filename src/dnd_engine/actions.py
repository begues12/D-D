"""Catalogo de intenciones estructuradas y su ejecucion contra el motor.

Esta es la frontera que separa "que quiere hacer alguien" de "que dicen las
reglas". La CLI construye `Intent` parseando texto; mas adelante el DM basado en
IA construira el mismo `Intent` a partir de lenguaje natural. Ninguno de los dos
decide resultados: eso lo hace el motor.

`action_schema()` devuelve el catalogo en forma serializable, para poder
entregarselo a un modelo como lista de acciones validas con sus parametros.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .game import GameEngine
from .models import Weapon


@dataclass(frozen=True)
class Intent:
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    actor_id: str | None = None


@dataclass(frozen=True)
class ActionResult:
    intent: Intent
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Parameter:
    name: str
    description: str
    kind: str = "str"
    required: bool = True


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    parameters: tuple[Parameter, ...] = ()
    handler: Callable[[GameEngine, Intent], ActionResult] = None  # type: ignore[assignment]
    needs_actor: bool = True


def _weapon_of(engine: GameEngine, actor_id: str, weapon_id: str | None) -> Weapon:
    actor = engine.world.get_character(actor_id)
    if weapon_id is not None:
        return actor.get_weapon(weapon_id)
    for item in actor.inventory:
        if isinstance(item, Weapon):
            return item
    raise ValueError(f"{actor.name} no lleva ningun arma.")


def _move(engine: GameEngine, intent: Intent) -> ActionResult:
    destination = (intent.parameters["x"], intent.parameters["y"])
    result = engine.move(intent.actor_id, destination)
    return ActionResult(
        intent,
        f"se mueve a {destination} gastando {result.cost_feet} pies "
        f"(le quedan {result.movement_left}).",
        {"cost_feet": result.cost_feet, "movement_left": result.movement_left},
    )


def _approach(engine: GameEngine, intent: Intent) -> ActionResult:
    target = engine.world.get_character(intent.parameters["target"])
    result = engine.approach(intent.actor_id, target.id)
    if result.cost_feet == 0:
        summary = f"ya esta junto a {target.name}."
    else:
        summary = (f"se acerca a {target.name} hasta {result.destination} gastando "
                   f"{result.cost_feet} pies (le quedan {result.movement_left}).")
    return ActionResult(intent, summary, {
        "target_id": target.id, "destination": result.destination,
        "cost_feet": result.cost_feet, "movement_left": result.movement_left,
    })


def _attack(engine: GameEngine, intent: Intent) -> ActionResult:
    weapon = _weapon_of(engine, intent.actor_id, intent.parameters.get("weapon"))
    target = engine.world.get_character(intent.parameters["target"])
    result = engine.attack(intent.actor_id, target.id, weapon.id)
    if not result.hit:
        outcome = f"falla el ataque contra {target.name}"
    elif result.critical:
        outcome = f"acierta un critico a {target.name} y le hace {result.damage} de dano"
    else:
        outcome = f"acierta a {target.name} y le hace {result.damage} de dano"
    detail = f"d20={result.natural_roll} total={result.total_attack}"
    if result.advantage.value != "none":
        detail += f" con {result.advantage.value} {result.rolls}"
    return ActionResult(
        intent, f"{outcome} con {weapon.name}. [{detail}] HP de {target.name}: {result.target_hp}.",
        {"hit": result.hit, "damage": result.damage, "target_hp": result.target_hp},
    )


def _cast(engine: GameEngine, intent: Intent) -> ActionResult:
    target = engine.world.get_character(intent.parameters["target"])
    spell_id = intent.parameters["spell"]
    result = engine.cast_spell(intent.actor_id, target.id, spell_id)
    spell = engine.world.get_character(intent.actor_id).get_spell(spell_id)
    if result.automatic_failure:
        save = "falla automaticamente la salvacion"
    elif result.saved:
        save = f"supera la salvacion con {result.saving_roll}"
    else:
        save = f"falla la salvacion con {result.saving_roll}"
    extra = f" y queda {result.condition_applied.value}" if result.condition_applied else ""
    return ActionResult(
        intent,
        f"lanza {spell.name} sobre {target.name}: {save}, recibe {result.damage} de dano{extra}. "
        f"HP de {target.name}: {result.target_hp}.",
        {"saved": result.saved, "damage": result.damage},
    )


def _take(engine: GameEngine, intent: Intent) -> ActionResult:
    item = engine.take_item(intent.actor_id, intent.parameters["item"])
    return ActionResult(intent, f"coge {item.name}.", {"item_id": item.id})


def _drop(engine: GameEngine, intent: Intent) -> ActionResult:
    item = engine.drop_item(intent.actor_id, intent.parameters["item"])
    return ActionResult(intent, f"deja {item.name} en el suelo.", {"item_id": item.id})


def _use(engine: GameEngine, intent: Intent) -> ActionResult:
    result = engine.use_item(
        intent.actor_id, intent.parameters["item"], intent.parameters.get("target"))
    who = "" if result.target_id == result.user_id else         f" sobre {engine.world.get_character(result.target_id).name}"
    if result.effect == "heal":
        outcome = f"recupera {result.healed} puntos de golpe"
    else:
        outcome = f"se le quita el estado '{result.cured}'"
    left = " (se agota)" if result.spent else f" (le quedan {result.uses_left} usos)"
    return ActionResult(
        intent, f"usa {result.item_name}{who}: {outcome}.{left}",
        {"healed": result.healed, "cured": result.cured, "spent": result.spent},
    )


def _use_door(engine: GameEngine, intent: Intent) -> ActionResult:
    location = engine.use_door(intent.actor_id, intent.parameters["door"])
    return ActionResult(intent, f"cruza la puerta y llega a {location.name}.",
                        {"location_id": location.id})


def _unlock_door(engine: GameEngine, intent: Intent) -> ActionResult:
    door = engine.unlock_door(intent.parameters["door"], intent.actor_id)
    return ActionResult(intent, f"abre la puerta '{door.id}'.", {"door_id": door.id})


def _travel(engine: GameEngine, intent: Intent) -> ActionResult:
    location = engine.enter_location(intent.actor_id, intent.parameters["location"])
    return ActionResult(intent, f"entra en {location.name}.", {"location_id": location.id})


def _end_turn(engine: GameEngine, intent: Intent) -> ActionResult:
    character = engine.next_turn()
    return ActionResult(intent, f"termina su turno; le toca a {character.name}.",
                        {"next_character_id": character.id})


def _heal(engine: GameEngine, intent: Intent) -> ActionResult:
    target_id = intent.parameters["target"]
    healed = engine.heal(target_id, intent.parameters["amount"])
    target = engine.world.get_character(target_id)
    return ActionResult(intent, f"cura {healed} puntos a {target.name} (HP {target.hp}).",
                        {"healed": healed, "hp": target.hp})


def _saving_throw(engine: GameEngine, intent: Intent) -> ActionResult:
    result = engine.saving_throw(
        intent.actor_id, intent.parameters["ability"], intent.parameters["dc"],
    )
    verdict = "supera" if result.success else "falla"
    return ActionResult(
        intent, f"{verdict} la salvacion de {result.ability} (total {result.total}).",
        {"success": result.success},
    )


def _death_save(engine: GameEngine, intent: Intent) -> ActionResult:
    result = engine.death_save(intent.actor_id)
    if result.revived:
        outcome = "saca un 20 natural y vuelve en si con 1 HP"
    elif result.dead:
        outcome = "acumula tres fallos y muere"
    elif result.stabilized:
        outcome = "acumula tres exitos y se estabiliza"
    else:
        outcome = f"lleva {result.successes} exitos y {result.failures} fallos"
    return ActionResult(intent, f"tira salvacion contra muerte ({result.natural_roll}): {outcome}.",
                        {"dead": result.dead, "stabilized": result.stabilized})


ACTIONS: dict[str, ActionSpec] = {
    spec.name: spec
    for spec in (
        ActionSpec("move", "Moverse a una casilla de la ubicacion actual.", (
            Parameter("x", "Columna de destino.", "int"),
            Parameter("y", "Fila de destino.", "int"),
        ), _move),
        ActionSpec("approach", "Acercarse a un personaje hasta una casilla libre adyacente.", (
            Parameter("target", "Id del personaje al que acercarse."),
        ), _approach),
        ActionSpec("attack", "Atacar a un objetivo con un arma del inventario.", (
            Parameter("target", "Id del objetivo."),
            Parameter("weapon", "Id del arma; por defecto la primera del inventario.",
                      required=False),
        ), _attack),
        ActionSpec("cast", "Lanzar un hechizo conocido sobre un objetivo.", (
            Parameter("spell", "Id del hechizo."),
            Parameter("target", "Id del objetivo."),
        ), _cast),
        ActionSpec("take", "Coger un objeto del suelo de la ubicacion actual.", (
            Parameter("item", "Id del objeto."),
        ), _take),
        ActionSpec("drop", "Dejar en el suelo un objeto del inventario.", (
            Parameter("item", "Id del objeto."),
        ), _drop),
        ActionSpec("use", "Usar un consumible del inventario, sobre uno mismo o "
                   "sobre alguien al lado.", (
            Parameter("item", "Id del objeto."),
            Parameter("target", "Id de quien lo recibe; por defecto uno mismo.",
                      required=False),
        ), _use),
        ActionSpec("use_door", "Cruzar una puerta estando junto a ella.", (
            Parameter("door", "Id de la puerta."),
        ), _use_door),
        ActionSpec("unlock_door", "Abrir una puerta cerrada con la llave adecuada.", (
            Parameter("door", "Id de la puerta."),
        ), _unlock_door),
        ActionSpec("travel", "Ir a una ubicacion conectada por una puerta abierta.", (
            Parameter("location", "Id de la ubicacion."),
        ), _travel),
        ActionSpec("end_turn", "Terminar el turno y pasar al siguiente participante.",
                   (), _end_turn),
        ActionSpec("heal", "Curar puntos de golpe a un personaje.", (
            Parameter("target", "Id del personaje."),
            Parameter("amount", "Puntos de golpe a recuperar.", "int"),
        ), _heal),
        ActionSpec("saving_throw", "Tirar una salvacion contra una dificultad.", (
            Parameter("ability", "Caracteristica: strength, dexterity, ..."),
            Parameter("dc", "Dificultad.", "int"),
        ), _saving_throw),
        ActionSpec("death_save", "Tirar una salvacion contra muerte.", (), _death_save),
    )
}


def execute(engine: GameEngine, intent: Intent) -> ActionResult:
    """Valida la intencion y la ejecuta. Todo error de reglas sale como ValueError."""
    spec = ACTIONS.get(intent.action)
    if spec is None:
        raise ValueError(f"Accion desconocida: '{intent.action}'.")
    if spec.needs_actor and intent.actor_id is None:
        raise ValueError(f"La accion '{intent.action}' necesita un personaje que la ejecute.")
    parameters = _coerce(spec, intent.parameters)
    return spec.handler(engine, Intent(intent.action, parameters, intent.actor_id))


def _coerce(spec: ActionSpec, given: dict[str, Any]) -> dict[str, Any]:
    known = {parameter.name for parameter in spec.parameters}
    for name in given:
        if name not in known:
            raise ValueError(f"'{spec.name}' no acepta el parametro '{name}'.")
    parameters: dict[str, Any] = {}
    for parameter in spec.parameters:
        if parameter.name not in given or given[parameter.name] is None:
            if parameter.required:
                raise ValueError(f"'{spec.name}' necesita el parametro '{parameter.name}'.")
            continue
        value = given[parameter.name]
        if parameter.kind == "int":
            try:
                value = int(value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"'{parameter.name}' debe ser un numero entero, no '{value}'."
                ) from error
        parameters[parameter.name] = value
    return parameters


def action_schema() -> list[dict[str, Any]]:
    """El catalogo en forma serializable, para documentarlo o dárselo a un modelo."""
    return [
        {
            "action": spec.name,
            "description": spec.description,
            "needs_actor": spec.needs_actor,
            "parameters": [
                {"name": parameter.name, "description": parameter.description,
                 "type": parameter.kind, "required": parameter.required}
                for parameter in spec.parameters
            ],
        }
        for spec in ACTIONS.values()
    ]
