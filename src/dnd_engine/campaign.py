"""Configuracion de la campana: que historia quiere montar el jugador.

Un `CampaignSetup` es la respuesta a esas preguntas. `build_campaign` lo
convierte en un `GameEngine` jugable.

Los escenarios son *planos* (`dict`), no codigo: locations, doors, enemies y
quest en forma de datos. Anadir uno es anadir una entrada a `SCENARIOS`, y ese
mismo formato es el que genera la fragua (`forge.py`) cuando el grupo prefiere
una aventura inventada: si `CampaignSetup.blueprint` viene lleno, manda sobre el
catalogo y `build_campaign` no nota la diferencia.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Any

from .forge import validate_scenario
from .game import GameEngine
from .map import Door, Grid
from .models import (
    AbilityScores,
    Consumable,
    Character,
    Condition,
    Enemy,
    ItemEffect,
    Item,
    Location,
    NPC,
    Objective,
    Quest,
    Spell,
    Weapon,
    World,
)

SETUP_KEY = "campaign_setup"


# -- catalogos ----------------------------------------------------------------


@dataclass(frozen=True)
class Tone:
    id: str
    name: str
    description: str
    guidance: str


TONES: dict[str, Tone] = {tone.id: tone for tone in (
    Tone("heroico", "Heroico",
         "Aventura clasica, valor y grandes gestos.",
         "Narra con energia y sentido de la aventura. Los golpes son vistosos y "
         "el peligro se siente, pero el tono es luminoso."),
    Tone("oscuro", "Oscuro",
         "Fantasia sombria, todo cuesta caro.",
         "Narra con sobriedad y desasosiego. Insiste en el frio, el cansancio y "
         "lo que se pierde. Nada de heroismo comodo."),
    Tone("misterio", "Misterio",
         "Investigacion, pistas y cosas que no encajan.",
         "Narra fijandote en detalles que sugieren mas de lo que muestran. "
         "Deja preguntas abiertas sin inventar respuestas."),
    Tone("humor", "Humor",
         "Comedia de aventuras, desastres con gracia.",
         "Narra con humor seco. Los fallos son comicos, nunca crueles. No "
         "rompas la ficcion con chistes sobre el propio juego."),
    Tone("crudo", "Crudo",
         "Supervivencia, heridas que pesan.",
         "Narra de forma seca y fisica. Cada herida y cada recurso gastado "
         "importan. Frases cortas."),
)}


@dataclass(frozen=True)
class Archetype:
    id: str
    name: str
    description: str
    abilities: dict[str, int]
    max_hp: int
    armor_class: int
    weapon: dict[str, Any]
    items: tuple[dict[str, str], ...] = ()
    spells: tuple[dict[str, Any], ...] = ()
    spell_slots: dict[int, int] = field(default_factory=dict)


# Nota: el motor usa siempre el modificador de Fuerza al atacar (no hay armas
# de finesse todavia), asi que los arquetipos agiles lo compensan con el
# bonificador del arma en vez de con Destreza.
ARCHETYPES: dict[str, Archetype] = {one.id: one for one in (
    Archetype(
        "guerrero", "Guerrero", "Aguanta y pega. El mas sencillo de llevar.",
        {"strength": 16, "dexterity": 12, "constitution": 15},
        max_hp=22, armor_class=16,
        weapon={"id": "longsword", "name": "Espada larga", "damage": "1d8+3", "attack_bonus": 5, "reach": 5},
        items=({"id": "shield", "name": "Escudo"},
               {"id": "rations", "name": "Raciones de viaje"},
               {"id": "potion", "name": "Pocion de curacion",
                "effect": "heal", "healing": "1d8+2"}),
    ),
    Archetype(
        "explorador", "Explorador", "Golpea de lejos y se mueve bien.",
        {"strength": 13, "dexterity": 16, "constitution": 13},
        max_hp=17, armor_class=14,
        weapon={"id": "shortbow", "name": "Arco corto", "damage": "1d6+3", "attack_bonus": 6, "reach": 80},
        items=({"id": "rope", "name": "Cuerda de canamo"},
               {"id": "torch", "name": "Antorcha"},
               {"id": "potion", "name": "Pocion de curacion",
                "effect": "heal", "healing": "1d8+2"}),
    ),
    Archetype(
        "mago", "Mago", "Fragil, pero cambia el combate con un hechizo.",
        {"strength": 10, "dexterity": 14, "constitution": 12, "intelligence": 16},
        max_hp=13, armor_class=12,
        weapon={"id": "dagger", "name": "Daga", "damage": "1d4+1", "attack_bonus": 3, "reach": 5},
        items=({"id": "spellbook", "name": "Libro de conjuros"},
               {"id": "potion", "name": "Pocion de curacion",
                "effect": "heal", "healing": "1d8+2"}),
        spells=({"id": "firebolt", "name": "Rayo de fuego", "level": 1, "damage": "1d8+2", "saving_ability": "dexterity", "save_dc": 14,
                 "range_feet": 60},
                {"id": "hold", "name": "Sujetar persona", "level": 1,
                 "saving_ability": "wisdom", "save_dc": 14, "condition": "paralyzed",
                 "duration_rounds": 3, "range_feet": 30}),
        spell_slots={1: 3},
    ),
    Archetype(
        "picaro", "Picaro", "Poco aguante, mucha iniciativa y ganzuas.",
        {"strength": 12, "dexterity": 16, "constitution": 12, "charisma": 14},
        max_hp=15, armor_class=14,
        weapon={"id": "dagger", "name": "Daga arrojadiza", "damage": "1d4+3", "attack_bonus": 6, "reach": 20},
        items=({"id": "lockpicks", "name": "Ganzuas"},
               {"id": "cloak", "name": "Capa raida"},
               {"id": "potion", "name": "Pocion de curacion",
                "effect": "heal", "healing": "1d8+2"}),
    ),
)}


@dataclass(frozen=True)
class Difficulty:
    id: str
    name: str
    description: str
    hp_scale: float
    armor_delta: int


DIFFICULTIES: dict[str, Difficulty] = {one.id: one for one in (
    Difficulty("facil", "Facil", "Los enemigos aguantan menos y aciertan peor.", 0.7, -1),
    Difficulty("normal", "Normal", "Como esta escrito el escenario.", 1.0, 0),
    Difficulty("dificil", "Dificil", "Los enemigos aguantan mas y son mas dificiles de tocar.", 1.5, 2),
)}


# -- escenarios como planos ---------------------------------------------------

SCENARIOS: dict[str, dict[str, Any]] = {
    "taberna": {
        "name": "El sotano del Dragon Rojo",
        "description": "Algo sube por la trampilla de la bodega cada noche.",
        "intro": (
            "Marta lleva ocho noches durmiendo con el hacha al lado de la cama. "
            "Dice que del sotano sube un raspar de unas contra la piedra, y que "
            "cada manana falta algo: un jamon, un barril, el gato. Nadie del pueblo "
            "quiere bajar. Ella paga bien y no hace preguntas."
        ),
        "start": "tavern",
        "locations": [
            {"id": "tavern", "name": "Taberna del Dragon Rojo",
             "description": "Suelo pegajoso, tres parroquianos y una trampilla al fondo.",
             "items": [{"id": "cellar-key", "name": "Llave de la bodega",
                        "description": "Colgada de un clavo detras de la barra."}]},
            {"id": "cellar", "name": "Bodega",
             "description": "Barriles hasta el techo y olor a moho.",
             "grid": {"width": 6, "height": 4, "blocked": [[2, 1], [2, 2], [4, 0]]},
             "items": [{"id": "cellar-brew", "name": "Frasco de aguardiente", "cell": [1, 3],
                        "description": "Marta lo escondia aqui.", "effect": "heal",
                        "healing": "1d6+1"}]},
            {"id": "tunnel", "name": "Tunel excavado",
             "description": "Alguien ha abierto un paso en la pared de la bodega.",
             "grid": {"width": 5, "height": 3, "blocked": [[2, 0]]}},
        ],
        "doors": [
            {"id": "trapdoor", "a": "tavern", "b": "cellar", "cell_b": [0, 0],
             "locked": True, "key_id": "cellar-key"},
            {"id": "breach", "a": "cellar", "b": "tunnel", "cell_a": [5, 3], "cell_b": [0, 2]},
        ],
        "npcs": [
            {"id": "innkeeper", "name": "Marta la tabernera", "location": "tavern",
             "personality": ["seca", "practica", "no se asusta delante de nadie"],
             "goals": ["Recuperar la bodega antes de que se pierda la cosecha"],
             "knowledge": [
                 "Los ruidos empezaron hace ocho noches.",
                 "La llave de la bodega esta detras de la barra, en un clavo.",
                 "El gato bajo el martes y no ha vuelto a subir.",
                 "En la pared del fondo de la bodega hay un boquete que ella no abrio.",
             ]},
            {"id": "drunk", "name": "El viejo Cass", "location": "tavern",
             "personality": ["borracho", "solemne", "se cree escuchado"],
             "goals": ["Que alguien le pague otra ronda"],
             "knowledge": [
                 "Dice que oyo cantar bajo el suelo, en una lengua que no es la nuestra.",
                 "Jura que hace cuarenta anos taparon un pozo justo donde esta la taberna.",
                 "Se acuerda del nombre Zarpa, y no sabe de que.",
             ]},
        ],
        "enemies": [
            {"id": "goblin-1", "name": "Goblin carronero", "max_hp": 9, "armor_class": 13,
             "xp": 50, "location": "cellar", "cell": [5, 3],
             "abilities": {"strength": 12, "dexterity": 14},
             "weapon": {"name": "Cimitarra", "damage": "1d6+1",
                        "attack_bonus": 4}},
            {"id": "goblin-boss", "name": "Zarpa, jefe goblin", "max_hp": 18,
             "armor_class": 15, "xp": 200, "location": "tunnel", "cell": [4, 1],
             "abilities": {"strength": 14, "dexterity": 14},
             "weapon": {"name": "Hacha mellada", "damage": "1d8+2",
                        "attack_bonus": 5}},
        ],
        "quest": {
            "id": "cellar-threat", "name": "Lo que hay bajo la taberna",
            "objectives": [
                {"id": "reach-tunnel", "description": "Encontrar el tunel",
                 "event_type": "PLAYER_ENTERED_LOCATION", "target_id": "tunnel"},
                {"id": "kill-boss", "description": "Acabar con Zarpa",
                 "event_type": "NPC_DIES", "target_id": "goblin-boss"},
            ],
        },
    },
    "cripta": {
        "name": "La cripta del Rey Sin Nombre",
        "description": "Bajo la colina duerme algo que la aldea prefiere no nombrar.",
        "intro": (
            "La aldea enterro a su ultimo rey sin escribir su nombre, para que nadie "
            "pudiera llamarlo de vuelta. Llevo ocho siglos funcionando. Hace tres "
            "semanas un pastor movio el sello de piedra buscando refugio de la "
            "tormenta, y desde entonces los perros no se acercan a la colina."
        ),
        "start": "vestibule",
        "locations": [
            {"id": "vestibule", "name": "Vestibulo de la cripta",
             "description": "Columnas rotas y un sello de piedra en el suelo.",
             "grid": {"width": 6, "height": 5, "blocked": [[1, 2], [4, 2]]}},
            {"id": "gallery", "name": "Galeria de los sarcofagos",
             "description": "Doce nichos, once abiertos.",
             "grid": {"width": 7, "height": 5,
                      "blocked": [[2, 1], [2, 2], [4, 1], [4, 2], [3, 4]]},
             "items": [{"id": "bone-key", "name": "Llave de hueso", "cell": [3, 0],
                        "description": "En la mano seca del duodecimo nicho."},
                       {"id": "grave-goods", "name": "Ajuar funerario", "cell": [1, 4],
                        "description": "Monedas verdes de moho."},
                       {"id": "grave-balm", "name": "Balsamo funerario", "cell": [6, 4],
                        "description": "Aun huele a resina.", "effect": "heal",
                        "healing": "1d8+1", "uses": 2}]},
            {"id": "throne", "name": "Camara del trono",
             "description": "Un asiento de basalto y una corona sin cabeza.",
             "grid": {"width": 5, "height": 5, "blocked": [[2, 2]]}},
        ],
        "doors": [
            {"id": "stone-seal", "a": "vestibule", "b": "gallery",
             "cell_a": [5, 2], "cell_b": [0, 2]},
            {"id": "throne-gate", "a": "gallery", "b": "throne",
             "cell_a": [6, 2], "cell_b": [0, 2], "locked": True, "key_id": "bone-key"},
        ],
        "npcs": [
            {"id": "shepherd", "name": "Ordo, el pastor", "location": "vestibule",
             "cell": [0, 4],
             "personality": ["culpable", "callado", "no entra en la cripta"],
             "goals": ["Que alguien vuelva a poner el sello y no le culpen"],
             "knowledge": [
                 "Movio el sello de piedra hace tres semanas, buscando refugio.",
                 "Desde esa noche los perros no suben a la colina.",
                 "Dentro hay doce nichos y solo uno seguia cerrado.",
                 "Al rey lo enterraron sin nombre para que nadie pudiera llamarlo.",
             ]},
        ],
        "enemies": [
            {"id": "skeleton-1", "name": "Esqueleto", "max_hp": 11, "armor_class": 13,
             "xp": 50, "location": "vestibule", "cell": [5, 4],
             "abilities": {"strength": 12, "dexterity": 14},
             "weapon": {"name": "Espada corta oxidada", "damage": "1d6+1",
                        "attack_bonus": 4}},
            {"id": "skeleton-2", "name": "Esqueleto arquero", "max_hp": 9, "armor_class": 13,
             "xp": 50, "location": "gallery", "cell": [6, 0],
             "abilities": {"strength": 10, "dexterity": 16},
             "weapon": {"name": "Arco podrido", "damage": "1d6",
                        "attack_bonus": 4, "reach": 60}},
            {"id": "barrow-king", "name": "El Rey Sin Nombre", "max_hp": 30,
             "armor_class": 16, "xp": 450, "location": "throne", "cell": [2, 0],
             "abilities": {"strength": 16, "dexterity": 12},
             "weapon": {"name": "Espada de tumulo", "damage": "1d10+3",
                        "attack_bonus": 6}},
        ],
        "quest": {
            "id": "silence-the-king", "name": "Callar al Rey",
            "objectives": [
                {"id": "kill-king", "description": "Destruir al Rey Sin Nombre",
                 "event_type": "NPC_DIES", "target_id": "barrow-king"},
            ],
        },
    },
    "torre": {
        "name": "La torre del alquimista",
        "description": "El alquimista lleva un mes sin bajar, y su torre zumba.",
        "intro": (
            "El alquimista subio a su laboratorio hace un mes y no ha vuelto a bajar. "
            "Su aprendiza Nel siguio dejandole la comida en el segundo peldano hasta "
            "que empezo a encontrarla intacta y cubierta de un polvo verde. La torre "
            "zumba de noche. Ella os ha abierto la puerta y no piensa subir."
        ),
        "start": "stairs",
        "locations": [
            {"id": "stairs", "name": "Escalera de caracol",
             "description": "Peldanos gastados y un olor acido que baja.",
             "grid": {"width": 4, "height": 4, "blocked": [[1, 1], [2, 2]]}},
            {"id": "lab", "name": "Laboratorio",
             "description": "Mesas volcadas, cristal por el suelo, algo que aun burbujea.",
             "grid": {"width": 7, "height": 6,
                      "blocked": [[2, 2], [3, 2], [4, 2], [2, 3], [4, 3]]},
             "items": [{"id": "brass-key", "name": "Llave de laton", "cell": [5, 4],
                        "description": "En el bolsillo de una bata colgada."},
                       {"id": "black-flask", "name": "Frasco negro", "cell": [3, 1],
                        "description": "Vacio, y aun asi pesa."},
                       {"id": "green-draught", "name": "Brebaje verde", "cell": [0, 5],
                        "description": "Etiquetado con letra apresurada.",
                        "effect": "heal", "healing": "1d10"}]},
            {"id": "roof", "name": "Azotea",
             "description": "Viento, un pararrayos torcido y el cielo demasiado cerca.",
             "grid": {"width": 5, "height": 5}},
        ],
        "doors": [
            {"id": "lab-door", "a": "stairs", "b": "lab", "cell_a": [3, 0], "cell_b": [0, 0]},
            {"id": "hatch", "a": "lab", "b": "roof", "cell_a": [6, 5], "cell_b": [0, 4],
             "locked": True, "key_id": "brass-key"},
        ],
        "npcs": [
            {"id": "apprentice", "name": "Nel, la aprendiza", "location": "stairs",
             "personality": ["asustada", "leal", "habla deprisa cuando miente"],
             "goals": ["Sacar al maestro de ahi arriba, sea lo que sea que quede de el"],
             "knowledge": [
                 "El maestro dejo de responder tras abrir el frasco negro.",
                 "Lo que baja por la escalera huele a vinagre y a pelo quemado.",
                 "La puerta del laboratorio se cierra sola desde dentro.",
                 "El maestro llevaba tres noches sin dormir antes de subir a la azotea.",
             ]},
        ],
        "enemies": [
            {"id": "homunculus-1", "name": "Homunculo", "max_hp": 10, "armor_class": 13,
             "xp": 50, "location": "lab", "cell": [6, 0],
             "abilities": {"strength": 10, "dexterity": 16},
             "weapon": {"name": "Dientes de vidrio", "damage": "1d4+2",
                        "attack_bonus": 5}},
            {"id": "homunculus-2", "name": "Homunculo deforme", "max_hp": 14,
             "armor_class": 14, "xp": 100, "location": "lab", "cell": [6, 5],
             "abilities": {"strength": 14, "dexterity": 12},
             "weapon": {"name": "Brazo fundido", "damage": "1d6+2",
                        "attack_bonus": 5}},
            {"id": "the-thing", "name": "Lo que quedo del alquimista", "max_hp": 26,
             "armor_class": 15, "xp": 450, "location": "roof", "cell": [2, 0],
             "abilities": {"strength": 16, "dexterity": 10},
             "weapon": {"name": "Zarpa acida", "damage": "1d8+4",
                        "attack_bonus": 6}},
        ],
        "quest": {
            "id": "the-grimoire", "name": "El grimorio del alquimista",
            "objectives": [
                {"id": "reach-roof", "description": "Subir a la azotea",
                 "event_type": "PLAYER_ENTERED_LOCATION", "target_id": "roof"},
                {"id": "end-it", "description": "Terminar con lo que quedo del alquimista",
                 "event_type": "NPC_DIES", "target_id": "the-thing"},
            ],
        },
    },
    "pantano": {
        "name": "El vado de los ahogados",
        "description": "Tres carros han desaparecido en el vado este mes.",
        "intro": (
            "Tres carros han entrado en el vado este mes y ninguno ha salido por el "
            "otro lado. No hay restos, no hay sangre, no hay huellas de vuelta: solo "
            "roderas que se meten en el agua negra. Bran, el ultimo carretero que se "
            "atrevio, os espera en la orilla y no suelta el farol."
        ),
        "start": "shore",
        "locations": [
            {"id": "shore", "name": "Orilla del vado",
             "description": "Juncos altos y roderas que entran en el agua y no salen.",
             "grid": {"width": 6, "height": 4, "blocked": [[3, 0], [3, 1]]}},
            {"id": "islet", "name": "Islote de sauces",
             "description": "Un monticulo de barro con sauces que no deberian crecer ahi.",
             "grid": {"width": 5, "height": 5, "blocked": [[1, 1], [3, 3]]},
             "items": [{"id": "carter-ledger", "name": "Libro de porte empapado",
                        "cell": [2, 4], "description": "De uno de los carros perdidos."},
                       {"id": "marsh-poultice", "name": "Cataplasma de juncos", "cell": [4, 2],
                        "description": "Alguien acampo aqui.", "effect": "heal",
                        "healing": "1d6+2"}]},
            {"id": "ruin", "name": "Ruina sumergida",
             "description": "Media capilla asomando del agua negra.",
             "grid": {"width": 6, "height": 4, "blocked": [[2, 1], [3, 1], [2, 2]]}},
        ],
        "doors": [
            {"id": "ford", "a": "shore", "b": "islet", "cell_a": [5, 2], "cell_b": [0, 2]},
            {"id": "crypt-mouth", "a": "islet", "b": "ruin", "cell_a": [4, 4], "cell_b": [0, 0]},
        ],
        "enemies": [
            {"id": "frog", "name": "Rana gigante", "max_hp": 12, "armor_class": 12,
             "xp": 50, "location": "islet", "cell": [4, 0],
             "abilities": {"strength": 13, "dexterity": 13},
             "weapon": {"name": "Mordisco", "damage": "1d6+1",
                        "attack_bonus": 4}},
            {"id": "lizardfolk", "name": "Hombre-lagarto", "max_hp": 16, "armor_class": 15,
             "xp": 100, "location": "ruin", "cell": [5, 0],
             "abilities": {"strength": 15, "dexterity": 12},
             "weapon": {"name": "Lanza de hueso", "damage": "1d8+2",
                        "attack_bonus": 5, "reach": 10}},
            {"id": "drowned-priest", "name": "El sacerdote ahogado", "max_hp": 28,
             "armor_class": 14, "xp": 450, "location": "ruin", "cell": [5, 3],
             "abilities": {"strength": 15, "dexterity": 10},
             "weapon": {"name": "Cadena de incensario", "damage": "1d8+3",
                        "attack_bonus": 5, "reach": 10}},
        ],
        "npcs": [
            {"id": "carter", "name": "Bran, el carretero", "location": "shore",
             "personality": ["nervioso", "supersticioso", "no mira el agua al hablar"],
             "goals": ["Cruzar el vado de dia y no volver a pasar por aqui"],
             "knowledge": [
                 "Solo desaparecen de noche.",
                 "Los carros aparecen despues rio abajo, vacios y sin una rueda.",
                 "Los caballos se paran solos antes de meter la pata en el agua.",
                 "Su hermano cruzo el martes y no ha llegado al otro lado.",
             ]},
        ],
        "quest": {
            "id": "the-ford", "name": "Los carros del vado",
            "objectives": [
                {"id": "reach-ruin", "description": "Llegar a la ruina sumergida",
                 "event_type": "PLAYER_ENTERED_LOCATION", "target_id": "ruin"},
                {"id": "kill-priest", "description": "Acabar con el sacerdote ahogado",
                 "event_type": "NPC_DIES", "target_id": "drowned-priest"},
            ],
        },
    },
}


# -- configuracion ------------------------------------------------------------


MAX_PLAYERS = 6


@dataclass
class PlayerSetup:
    name: str
    archetype: str = "guerrero"

    @property
    def id(self) -> str:
        return "hero-" + _slug(self.name)


@dataclass
class CampaignSetup:
    players: list[PlayerSetup] = field(
        default_factory=lambda: [PlayerSetup("Aldric", "guerrero")])
    scenario: str = "taberna"
    tone: str = "heroico"
    difficulty: str = "normal"
    premise: str = ""
    use_ai_dm: bool = False
    title: str = ""
    # Que IA narra y con que modelo. Vacio = lo que diga el entorno.
    ai_provider: str = ""
    ai_model: str = ""
    # Plano de una aventura inventada por la IA. Si esta, manda sobre `scenario`,
    # que pasa a ser solo su nombre corto.
    blueprint: dict[str, Any] | None = None

    @property
    def is_forged(self) -> bool:
        return self.blueprint is not None

    def validate(self) -> None:
        catalogs = [(self.tone, TONES, "tono"),
                    (self.difficulty, DIFFICULTIES, "dificultad")]
        if self.is_forged:
            validate_scenario(self.blueprint)
        else:
            catalogs.append((self.scenario, SCENARIOS, "escenario"))
        for value, catalog, what in catalogs:
            if value not in catalog:
                raise ValueError(
                    f"No existe el {what} '{value}'. Opciones: {', '.join(sorted(catalog))}."
                )
        if not self.players:
            raise ValueError("Hace falta al menos un jugador.")
        if len(self.players) > MAX_PLAYERS:
            raise ValueError(f"Como maximo {MAX_PLAYERS} jugadores.")
        seen: set[str] = set()
        for player in self.players:
            if not player.name.strip():
                raise ValueError("Cada jugador necesita un nombre.")
            if player.archetype not in ARCHETYPES:
                raise ValueError(
                    f"No existe el arquetipo '{player.archetype}'. "
                    f"Opciones: {', '.join(sorted(ARCHETYPES))}."
                )
            if player.id in seen:
                raise ValueError(f"Hay dos jugadores llamados '{player.name}'.")
            seen.add(player.id)

    @property
    def scenario_blueprint(self) -> dict[str, Any]:
        """El plano que se va a jugar, venga del catalogo o de la fragua."""
        return self.blueprint if self.is_forged else SCENARIOS[self.scenario]

    @property
    def campaign_title(self) -> str:
        return self.title or self.scenario_blueprint["name"]

    @property
    def party_size(self) -> int:
        return len(self.players)

    def to_dict(self) -> dict[str, Any]:
        return {
            "players": [{"name": one.name, "archetype": one.archetype}
                        for one in self.players],
            "scenario": self.scenario, "tone": self.tone, "difficulty": self.difficulty,
            "premise": self.premise, "use_ai_dm": self.use_ai_dm, "title": self.title,
            "ai_provider": self.ai_provider, "ai_model": self.ai_model,
            "blueprint": self.blueprint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CampaignSetup":
        values = {key: data[key] for key in data if key in cls.__dataclass_fields__}
        values["players"] = [
            PlayerSetup(one["name"], one.get("archetype", "guerrero"))
            for one in data.get("players", [])
        ] or [PlayerSetup("Aldric")]
        return cls(**values)

    def store_in(self, world: World) -> None:
        """La configuracion viaja en el estado del mundo, asi se guarda y carga sola."""
        world.state[SETUP_KEY] = self.to_dict()

    @classmethod
    def from_world(cls, world: World) -> "CampaignSetup | None":
        data = world.state.get(SETUP_KEY)
        return cls.from_dict(data) if data else None

    def summary(self) -> str:
        party = "\n".join(
            f"    - {one.name}, {ARCHETYPES[one.archetype].name}" for one in self.players)
        return "\n".join((
            f"  Campana:     {self.campaign_title}",
            f"  Escenario:   {self.scenario_blueprint['name']}"
            + ("  (inventada por la IA)" if self.is_forged else ""),
            f"  Tono:        {TONES[self.tone].name}",
            f"  Dificultad:  {DIFFICULTIES[self.difficulty].name}",
            f"  Grupo ({self.party_size}):",
            party,
            f"  Premisa:     {self.premise or '(ninguna)'}",
            f"  DM con IA:   {'si' if self.use_ai_dm else 'no'}"
            + (f" ({self.ai_model})" if self.use_ai_dm and self.ai_model else ""),
        ))


def story_brief(setup: CampaignSetup) -> str:
    """Bloque estable que se anade al prompt de sistema del DM."""
    scenario = setup.scenario_blueprint
    party = ", ".join(
        f"{one.name} ({one.id}, {ARCHETYPES[one.archetype].name})" for one in setup.players)
    lines = [
        "",
        "LA HISTORIA QUE SE ESTA JUGANDO",
        f"Campana: {setup.campaign_title}",
        f"Escenario: {scenario['name']}. {scenario['description']}",
        f"Grupo de {setup.party_size}: {party}.",
        f"Tono: {TONES[setup.tone].name}. {TONES[setup.tone].guidance}",
    ]
    if setup.premise:
        lines.append(f"El grupo ha pedido ademas: {setup.premise}")
    return "\n".join(lines)


def scenario_intro(setup: CampaignSetup) -> str:
    blueprint = setup.scenario_blueprint
    return blueprint.get("intro") or blueprint["description"]


def briefing(engine: GameEngine, actor_id: str, intro: str | None = None) -> str:
    """Apertura de la aventura: donde estais, quien sois y que os jugais.

    `intro` permite sustituir el gancho escrito del escenario por una narracion
    del DM, dejando intactos los datos duros de debajo.
    """
    world = engine.world.world
    setup = CampaignSetup.from_world(world)
    location = world.location_of(actor_id)
    plural = bool(setup and setup.party_size > 1)

    lines = ["=" * 64,
             "  " + (setup.campaign_title if setup else world.name).upper(),
             "=" * 64, ""]
    if intro is not None:
        lines += [_wrap(intro), ""]
    elif setup is not None:
        lines += [_wrap(scenario_intro(setup)), ""]

    if setup is not None:
        party = ", ".join(
            f"{one.name} ({ARCHETYPES[one.archetype].name.lower()})" for one in setup.players)
        lines.append(f"{'El grupo' if plural else 'Tu personaje'}: {party}.")
        if setup.premise:
            lines.append(_wrap(f"Lo que os trae aqui: {setup.premise}"))

    if location is not None:
        lines.append("")
        lines.append(_wrap(
            f"{'Estais' if plural else 'Estas'} en {location.name}."
            + (f" {location.description}" if location.description else "")))
        present = [world.characters[one].name for one in sorted(location.occupants)
                   if one != actor_id]
        if present:
            lines.append("Aqui hay: " + ", ".join(present) + ".")
        if location.items:
            lines.append("A la vista: " + ", ".join(
                f"{item.name} [{item.id}]" for item in location.items) + ".")
        exits = []
        for door in world.doors_of(location.id):
            if door.hidden:
                continue
            state = " (cerrada con llave)" if door.locked else ""
            exits.append(f"{door.id} hacia "
                         f"{world.get_location(door.other_side(location.id)).name}{state}")
        lines.append("Salidas: " + (", ".join(exits) if exits else "ninguna a la vista") + ".")

    pending = [
        (quest, [one for one in quest.objectives.values() if not one.completed])
        for quest in engine.quests.quests.values() if quest.status == "active"
    ]
    for quest, objectives in pending:
        lines.append("")
        lines.append(f"{quest.name}:")
        lines += [f"  - {one.description}" for one in objectives]

    if setup is not None:
        lines.append("")
        lines.append(f"Tono: {TONES[setup.tone].name.lower()}. "
                     f"Dificultad: {DIFFICULTIES[setup.difficulty].name.lower()}.")
    return "\n".join(lines)


def _wrap(text: str, width: int = 74) -> str:
    return "\n".join(textwrap.wrap(text, width)) or text


def _slug(name: str) -> str:
    cleaned = "".join(
        letter if letter.isalnum() else "-" for letter in name.strip().lower())
    return "-".join(part for part in cleaned.split("-") if part) or "sin-nombre"


# -- construccion del mundo ---------------------------------------------------

# Cada jugador de mas engrosa a los enemigos: si no, un grupo de cuatro barre
# el escenario sin despeinarse.
PARTY_HP_SCALE = 0.35


def build_campaign(setup: CampaignSetup, roller=None) -> GameEngine:
    """Convierte la configuracion en una partida lista para jugar."""
    setup.validate()
    blueprint = setup.scenario_blueprint
    difficulty = DIFFICULTIES[setup.difficulty]
    party_scale = 1 + PARTY_HP_SCALE * (setup.party_size - 1)

    world = World(setup.campaign_title)
    for data in blueprint["locations"]:
        world.add_location(Location(
            id=data["id"], name=data["name"], description=data.get("description", ""),
            grid=_grid(data.get("grid")),
            items=[_build_item(one) for one in data.get("items", [])],
        ))
    for data in blueprint["doors"]:
        world.add_door(Door(
            data["id"], data["a"], data["b"],
            _cell(data.get("cell_a")), _cell(data.get("cell_b")),
            data.get("locked", False), data.get("key_id"), data.get("hidden", False),
        ))

    engine = GameEngine(world, roller) if roller else GameEngine(world)
    for player in setup.players:
        hero = _build_player(player)
        engine.add_character(hero)
        engine.place(hero.id, blueprint["start"])

    for data in blueprint.get("npcs", []):
        npc = NPC(data["id"], data["name"],
                  personality=list(data.get("personality", [])),
                  knowledge=set(data.get("knowledge", [])),
                  goals=list(data.get("goals", [])))
        engine.add_character(npc)
        engine.place(npc.id, data["location"], _cell(data.get("cell")))

    for data in blueprint.get("enemies", []):
        engine.add_character(_build_enemy(data, difficulty, party_scale))
        engine.place(data["id"], data["location"], _cell(data.get("cell")))

    quest = blueprint.get("quest")
    if quest:
        engine.add_quest(Quest(
            quest["id"], quest["name"],
            objectives={
                one["id"]: Objective(one["id"], one["description"],
                                     one["event_type"], one.get("target_id"))
                for one in quest["objectives"]
            },
        ))

    setup.store_in(world)
    return engine


def _build_player(player: PlayerSetup) -> Character:
    archetype = ARCHETYPES[player.archetype]
    hero = Character(
        player.id, player.name.strip(),
        max_hp=archetype.max_hp, armor_class=archetype.armor_class,
        abilities=AbilityScores(**archetype.abilities),
    )
    hero.add_item(Weapon(**archetype.weapon))
    for item in archetype.items:
        hero.add_item(_build_item(item))
    for data in archetype.spells:
        values = dict(data)
        condition = values.pop("condition", None)
        spell = Spell(**values)
        if condition:
            spell.condition = Condition(condition)
        hero.spells.append(spell)
    hero.spell_slots = dict(archetype.spell_slots)
    return hero


def _build_enemy(data: dict[str, Any], difficulty: Difficulty, party_scale: float) -> Enemy:
    enemy = Enemy(
        data["id"], data["name"],
        max_hp=max(1, round(data["max_hp"] * difficulty.hp_scale * party_scale)),
        armor_class=data["armor_class"] + difficulty.armor_delta,
        abilities=AbilityScores(**data.get("abilities", {})),
        experience_reward=data.get("xp", 0),
    )
    weapon = dict(data["weapon"])
    enemy.add_item(Weapon(
        id=weapon.pop("id", f"{data['id']}-weapon"), name=weapon.pop("name"), **weapon,
    ))
    return enemy


def _build_item(data: dict[str, Any]) -> Item:
    common = (data["id"], data["name"], data.get("description", ""), _cell(data.get("cell")))
    if "effect" not in data:
        return Item(*common)
    return Consumable(
        *common, effect=ItemEffect(data["effect"]), healing=data.get("healing", "0"),
        uses=data.get("uses", 1),
        condition=Condition(data["condition"]) if data.get("condition") else None,
    )


def _grid(data: dict[str, Any] | None) -> Grid | None:
    if not data:
        return None
    return Grid(data["width"], data["height"],
                {tuple(cell) for cell in data.get("blocked", [])})


def _cell(value):
    return tuple(value) if value else None
