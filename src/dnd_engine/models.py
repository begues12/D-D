from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .dice import Dice
from .map import Cell, Door, Grid

# Una pocion sin dados: no cura nada por si sola.
FLAT_ZERO = Dice(0, 0, 0)


class Condition(str, Enum):
    POISONED = "poisoned"
    STUNNED = "stunned"
    BLINDED = "blinded"
    PARALYZED = "paralyzed"
    UNCONSCIOUS = "unconscious"


# Efecto mecanico de cada condicion. El motor consulta estos conjuntos; no hay
# reglas de condiciones dispersas por rules.py.
INCAPACITATING_CONDITIONS = frozenset({
    Condition.STUNNED, Condition.PARALYZED, Condition.UNCONSCIOUS,
})
SELF_DISADVANTAGE_CONDITIONS = frozenset({Condition.BLINDED, Condition.POISONED})
ATTACKER_ADVANTAGE_CONDITIONS = frozenset({
    Condition.BLINDED, Condition.STUNNED, Condition.PARALYZED, Condition.UNCONSCIOUS,
})
# Un personaje incapacitado falla automaticamente estas salvaciones.
AUTOFAIL_SAVE_ABILITIES = frozenset({"strength", "dexterity"})

DEFAULT_SPEED = 30
DEATH_SAVE_DC = 10
DEATH_SAVE_LIMIT = 3


@dataclass
class AbilityScores:
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    def modifier(self, ability: str) -> int:
        value = getattr(self, ability.lower())
        return (value - 10) // 2


@dataclass
class TurnResources:
    """Economia de turno: accion, accion adicional, reaccion y movimiento."""

    action: bool = True
    bonus_action: bool = True
    reaction: bool = True
    # Interaccion gratuita con un objeto por turno: coger, soltar, abrir.
    object_interaction: bool = True
    # None significa "sin resolver": Character lo fija a su velocidad al crearse.
    movement: int | None = None

    def reset(self, speed: int) -> None:
        self.action = True
        self.bonus_action = True
        self.reaction = True
        self.object_interaction = True
        self.movement = speed


@dataclass
class DeathSaves:
    successes: int = 0
    failures: int = 0

    def reset(self) -> None:
        self.successes = 0
        self.failures = 0


@dataclass
class Item:
    id: str
    name: str
    description: str = ""
    # Solo significa algo mientras el objeto esta en el suelo de una ubicacion
    # con cuadricula; al cogerlo vuelve a None.
    cell: Cell | None = None


class ItemEffect(str, Enum):
    HEAL = "heal"
    CURE = "cure"


@dataclass
class Consumable(Item):
    """Objeto de un solo uso (o varios): pociones, antidotos, vendas."""

    effect: ItemEffect = ItemEffect.HEAL
    # Cuanto cura: `2d4+2` o una cantidad fija como `5`. Irrelevante si el efecto es CURE.
    healing: Dice = FLAT_ZERO
    condition: Condition | None = None   # que estado quita, si el efecto es CURE
    uses: int = 1

    def __post_init__(self) -> None:
        self.healing = Dice.parse(self.healing)


@dataclass
class Weapon(Item):
    # El constructor acepta tambien la notacion: Weapon(..., damage="2d6+3").
    damage: Dice = Dice(1, 8)
    attack_bonus: int = 0
    reach: int = 5

    def __post_init__(self) -> None:
        self.damage = Dice.parse(self.damage)


@dataclass
class Spell(Item):
    level: int = 1
    damage: Dice | None = None
    saving_ability: str = "dexterity"
    save_dc: int = 10
    condition: Condition | None = None
    duration_rounds: int = 0
    range_feet: int = 30

    def __post_init__(self) -> None:
        if self.damage is not None:
            self.damage = Dice.parse(self.damage)


EXPERIENCE_THRESHOLDS = (0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000, 85000)


@dataclass
class Character:
    id: str
    name: str
    level: int = 1
    max_hp: int = 10
    armor_class: int = 10
    speed: int = DEFAULT_SPEED
    abilities: AbilityScores = field(default_factory=AbilityScores)
    hp: int | None = None
    inventory: list[Item] = field(default_factory=list)
    spells: list[Spell] = field(default_factory=list)
    spell_slots: dict[int, int] = field(default_factory=dict)
    conditions: set[Condition] = field(default_factory=set)
    condition_durations: dict[Condition, int] = field(default_factory=dict)
    experience: int = 0
    position: tuple[int, int] = (0, 0)
    resources: TurnResources = field(default_factory=TurnResources)
    death_saves: DeathSaves = field(default_factory=DeathSaves)
    # Las criaturas ordinarias mueren al llegar a 0 HP; los personajes jugadores
    # caen inconscientes y tiran salvaciones contra muerte.
    dies_at_zero_hp: bool = False
    is_dead: bool = False
    is_stable: bool = False

    def __post_init__(self) -> None:
        if self.hp is None:
            self.hp = self.max_hp
        if self.resources.movement is None:
            self.resources.movement = self.speed

    @property
    def is_alive(self) -> bool:
        """Sigue en la partida, aunque este agonizando."""
        return not self.is_dead

    @property
    def is_conscious(self) -> bool:
        return self.is_alive and Condition.UNCONSCIOUS not in self.conditions

    @property
    def is_dying(self) -> bool:
        return self.is_alive and self.hp == 0 and not self.is_stable

    @property
    def is_incapacitated(self) -> bool:
        return bool(self.conditions & INCAPACITATING_CONDITIONS)

    @property
    def can_act(self) -> bool:
        return self.is_alive and not self.is_incapacitated

    def begin_turn(self) -> None:
        self.resources.reset(self.speed)

    def add_item(self, item: Item) -> None:
        self.inventory.append(item)

    def get_weapon(self, weapon_id: str) -> Weapon:
        for item in self.inventory:
            if isinstance(item, Weapon) and item.id == weapon_id:
                return item
        raise ValueError(f"El personaje no tiene el arma '{weapon_id}'.")

    def get_item(self, item_id: str) -> Item:
        for item in self.inventory:
            if item.id == item_id:
                return item
        raise ValueError(f"El personaje no lleva ningun '{item_id}'.")

    def get_spell(self, spell_id: str) -> Spell:
        for spell in self.spells:
            if spell.id == spell_id:
                return spell
        raise ValueError(f"El personaje no conoce el hechizo '{spell_id}'.")

    def gain_experience(self, amount: int) -> list[int]:
        if amount < 0:
            raise ValueError("La experiencia no puede ser negativa.")
        previous_level = self.level
        self.experience += amount
        while self.level < len(EXPERIENCE_THRESHOLDS) and self.experience >= EXPERIENCE_THRESHOLDS[self.level]:
            self.level += 1
            self.max_hp += 1
            self.hp += 1
        return list(range(previous_level + 1, self.level + 1))


@dataclass
class NPC(Character):
    personality: list[str] = field(default_factory=list)
    knowledge: set[str] = field(default_factory=set)
    goals: list[str] = field(default_factory=list)
    relationships: dict[str, int] = field(default_factory=dict)
    secrets: list[str] = field(default_factory=list)


@dataclass
class Enemy(Character):
    experience_reward: int = 0
    dies_at_zero_hp: bool = True


@dataclass
class Objective:
    id: str
    description: str
    event_type: str
    target_id: str | None = None
    completed: bool = False


@dataclass
class Quest:
    id: str
    name: str
    objectives: dict[str, Objective] = field(default_factory=dict)
    optional_objectives: dict[str, Objective] = field(default_factory=dict)
    fail_event_types: set[str] = field(default_factory=set)
    status: str = "active"


@dataclass
class Location:
    id: str
    name: str
    description: str = ""
    # Sin cuadricula la ubicacion es "teatro de la mente": no hay posiciones ni
    # distancias, y el motor no valida movimiento ni alcance dentro de ella.
    grid: Grid | None = None
    occupants: set[str] = field(default_factory=set)
    items: list[Item] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class World:
    name: str
    locations: dict[str, Location] = field(default_factory=dict)
    characters: dict[str, Character] = field(default_factory=dict)
    doors: dict[str, Door] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)

    def add_location(self, location: Location) -> None:
        self.locations[location.id] = location

    def get_location(self, location_id: str) -> Location:
        try:
            return self.locations[location_id]
        except KeyError as error:
            raise ValueError(f"La ubicacion '{location_id}' no existe.") from error

    def add_character(self, character: Character, location_id: str | None = None) -> None:
        self.characters[character.id] = character
        if location_id is not None:
            self.move_character(character.id, location_id)

    def move_character(self, character_id: str, location_id: str) -> None:
        """Coloca a un personaje sin validar puertas: sirve para preparar la escena."""
        self.get_location(location_id)
        if character_id not in self.characters:
            raise ValueError(f"El personaje '{character_id}' no existe.")
        for location in self.locations.values():
            location.occupants.discard(character_id)
        self.locations[location_id].occupants.add(character_id)

    def location_of(self, character_id: str) -> Location | None:
        for location in self.locations.values():
            if character_id in location.occupants:
                return location
        return None

    def add_door(self, door: Door) -> Door:
        self.get_location(door.location_a)
        self.get_location(door.location_b)
        if door.id in self.doors:
            raise ValueError(f"La puerta '{door.id}' ya existe.")
        self.doors[door.id] = door
        return door

    def connect(
        self,
        location_a: str,
        location_b: str,
        door_id: str | None = None,
        **options: Any,
    ) -> Door:
        return self.add_door(Door(
            door_id or f"{location_a}--{location_b}", location_a, location_b, **options,
        ))

    def get_door(self, door_id: str) -> Door:
        try:
            return self.doors[door_id]
        except KeyError as error:
            raise ValueError(f"La puerta '{door_id}' no existe.") from error

    def doors_of(self, location_id: str) -> list[Door]:
        return [door for door in self.doors.values() if door.connects(location_id)]

    def door_between(self, location_a: str, location_b: str) -> Door | None:
        for door in self.doors.values():
            if door.connects(location_a) and door.connects(location_b) and location_a != location_b:
                return door
        return None

    def occupied_cells(self, location_id: str, ignore: str | None = None) -> set[Cell]:
        location = self.get_location(location_id)
        return {
            self.characters[occupant].position
            for occupant in location.occupants
            if occupant != ignore and occupant in self.characters
            and self.characters[occupant].is_alive
        }
