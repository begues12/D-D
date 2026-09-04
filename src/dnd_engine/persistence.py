from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .dice import Dice
from .events import Event
from .game import GameEngine
from .map import Door, Grid
from .models import (
    DEFAULT_SPEED,
    AbilityScores,
    Character,
    Condition,
    Consumable,
    DeathSaves,
    Enemy,
    Item,
    Location,
    NPC,
    Objective,
    Quest,
    ItemEffect,
    Spell,
    TurnResources,
    Weapon,
    World,
)


def save_game(engine: GameEngine, path: str | Path) -> None:
    payload = {
        "world": _world_to_dict(engine.world.world),
        "quests": [_quest_to_dict(quest) for quest in engine.quests.quests.values()],
        "events": [_event_to_dict(event) for event in engine.events.history],
        "memory": engine.memory.to_dict(),
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_game(path: str | Path) -> GameEngine:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    world = _world_from_dict(payload["world"])
    engine = GameEngine(world)
    for quest_data in payload.get("quests", []):
        engine.add_quest(_quest_from_dict(quest_data))
    engine.events.history = [_event_from_dict(event) for event in payload.get("events", [])]
    if "memory" in payload:
        engine.memory.load(payload["memory"])
    return engine


def _world_to_dict(world: World) -> dict[str, Any]:
    return {
        "name": world.name,
        "state": world.state,
        "locations": [_location_to_dict(location) for location in world.locations.values()],
        "doors": [_door_to_dict(door) for door in world.doors.values()],
        "characters": [_character_to_dict(character) for character in world.characters.values()],
    }


def _world_from_dict(data: dict[str, Any]) -> World:
    world = World(data["name"], state=data.get("state", {}))
    for location_data in data.get("locations", []):
        world.add_location(Location(
            id=location_data["id"], name=location_data["name"],
            description=location_data.get("description", ""),
            grid=_grid_from_dict(location_data.get("grid")),
            occupants=set(location_data.get("occupants", [])),
            items=[_item_from_dict(item) for item in location_data.get("items", [])],
            properties=location_data.get("properties", {}),
        ))
    for door_data in data.get("doors", []):
        world.add_door(_door_from_dict(door_data))
    _migrate_connected_locations(world, data.get("locations", []))
    for character_data in data.get("characters", []):
        character = _character_from_dict(character_data)
        world.add_character(character)
    return world


def _migrate_connected_locations(world: World, locations: list[dict[str, Any]]) -> None:
    """Partidas anteriores a las puertas guardaban vecinos sueltos por ubicacion."""
    for location_data in locations:
        origin = location_data["id"]
        for neighbour in sorted(location_data.get("connected_locations", [])):
            if neighbour in world.locations and world.door_between(origin, neighbour) is None:
                world.connect(origin, neighbour)


def _location_to_dict(location: Location) -> dict[str, Any]:
    return {
        "id": location.id, "name": location.name, "description": location.description,
        "grid": _grid_to_dict(location.grid),
        "occupants": sorted(location.occupants),
        "items": [_item_to_dict(item) for item in location.items],
        "properties": location.properties,
    }


def _grid_to_dict(grid: Grid | None) -> dict[str, Any] | None:
    if grid is None:
        return None
    return {"width": grid.width, "height": grid.height,
            "blocked": sorted(list(cell) for cell in grid.blocked)}


def _grid_from_dict(data: dict[str, Any] | None) -> Grid | None:
    if not data:
        return None
    return Grid(data["width"], data["height"], {tuple(cell) for cell in data.get("blocked", [])})


def _door_to_dict(door: Door) -> dict[str, Any]:
    return {"id": door.id, "location_a": door.location_a, "location_b": door.location_b,
            "cell_a": list(door.cell_a) if door.cell_a else None,
            "cell_b": list(door.cell_b) if door.cell_b else None,
            "locked": door.locked, "key_id": door.key_id, "hidden": door.hidden}


def _door_from_dict(data: dict[str, Any]) -> Door:
    return Door(
        data["id"], data["location_a"], data["location_b"],
        tuple(data["cell_a"]) if data.get("cell_a") else None,
        tuple(data["cell_b"]) if data.get("cell_b") else None,
        data.get("locked", False), data.get("key_id"), data.get("hidden", False),
    )


def _character_to_dict(character: Character) -> dict[str, Any]:
    data: dict[str, Any] = {
        "kind": "enemy" if isinstance(character, Enemy) else "npc" if isinstance(character, NPC) else "character",
        "id": character.id, "name": character.name, "level": character.level,
        "max_hp": character.max_hp, "hp": character.hp, "armor_class": character.armor_class,
        "speed": character.speed,
        "abilities": vars(character.abilities), "inventory": [_item_to_dict(item) for item in character.inventory],
        "spells": [_item_to_dict(spell) for spell in character.spells],
        "spell_slots": character.spell_slots, "conditions": [condition.value for condition in character.conditions],
        "condition_durations": {condition.value: duration for condition, duration in character.condition_durations.items()},
        "experience": character.experience, "position": list(character.position),
        "resources": vars(character.resources), "death_saves": vars(character.death_saves),
        "dies_at_zero_hp": character.dies_at_zero_hp, "is_dead": character.is_dead,
        "is_stable": character.is_stable,
    }
    if isinstance(character, Enemy):
        data["experience_reward"] = character.experience_reward
    if isinstance(character, NPC):
        data.update({
            "personality": character.personality, "knowledge": sorted(character.knowledge),
            "goals": character.goals, "relationships": character.relationships, "secrets": character.secrets,
        })
    return data


def _character_from_dict(data: dict[str, Any]) -> Character:
    common = {
        "id": data["id"], "name": data["name"], "level": data["level"],
        "max_hp": data["max_hp"], "hp": data["hp"], "armor_class": data["armor_class"],
        "speed": data.get("speed", DEFAULT_SPEED),
        "abilities": AbilityScores(**data["abilities"]),
        "inventory": [_item_from_dict(item) for item in data.get("inventory", [])],
        "spells": [_item_from_dict(spell) for spell in data.get("spells", [])],
        "spell_slots": {int(level): amount for level, amount in data.get("spell_slots", {}).items()},
        "conditions": {Condition(value) for value in data.get("conditions", [])},
        "condition_durations": {Condition(value): duration for value, duration in data.get("condition_durations", {}).items()},
        "experience": data.get("experience", 0), "position": tuple(data.get("position", [0, 0])),
        "resources": _resources_from_dict(data),
        "death_saves": DeathSaves(**data.get("death_saves", {})),
        "dies_at_zero_hp": data.get("dies_at_zero_hp", data["kind"] == "enemy"),
        "is_dead": data.get("is_dead", False), "is_stable": data.get("is_stable", False),
    }
    if data["kind"] == "enemy":
        return Enemy(**common, experience_reward=data.get("experience_reward", 0))
    if data["kind"] == "npc":
        return NPC(**common, personality=data.get("personality", []), knowledge=set(data.get("knowledge", [])),
                    goals=data.get("goals", []), relationships=data.get("relationships", {}), secrets=data.get("secrets", []))
    return Character(**common)


def _resources_from_dict(data: dict[str, Any]) -> TurnResources:
    speed = data.get("speed", DEFAULT_SPEED)
    if "resources" not in data:
        # Partidas guardadas antes de la economia de turno solo tenian la accion.
        return TurnResources(action=data.get("action_available", True), movement=speed)
    saved = data["resources"]
    movement = saved.get("movement")
    return TurnResources(
        action=saved.get("action", True), bonus_action=saved.get("bonus_action", True),
        reaction=saved.get("reaction", True),
        object_interaction=saved.get("object_interaction", True),
        movement=speed if movement is None else movement,
    )


def _item_to_dict(item: Item) -> dict[str, Any]:
    data = _item_body(item)
    # La casilla solo esta puesta mientras el objeto sigue en el suelo.
    data["cell"] = list(item.cell) if item.cell else None
    return data


def _item_body(item: Item) -> dict[str, Any]:
    if isinstance(item, Consumable):
        return {"kind": "consumable", "id": item.id, "name": item.name,
                "description": item.description, "effect": item.effect.value,
                "healing": str(item.healing), "uses": item.uses,
                "condition": item.condition.value if item.condition else None}
    if isinstance(item, Weapon):
        return {"kind": "weapon", "id": item.id, "name": item.name, "description": item.description,
                "damage": str(item.damage), "attack_bonus": item.attack_bonus,
                "reach": item.reach}
    if isinstance(item, Spell):
        return {"kind": "spell", "id": item.id, "name": item.name, "description": item.description,
                "level": item.level,
                "damage": str(item.damage) if item.damage is not None else None,
                "saving_ability": item.saving_ability, "save_dc": item.save_dc,
                "condition": item.condition.value if item.condition else None,
                "duration_rounds": item.duration_rounds, "range_feet": item.range_feet}
    return {"kind": "item", "id": item.id, "name": item.name, "description": item.description}


def _item_from_dict(data: dict[str, Any]) -> Item:
    if data["kind"] == "consumable":
        return _with_cell(Consumable(
            data["id"], data["name"], data.get("description", ""),
            effect=ItemEffect(data.get("effect", "heal")), healing=_healing_of(data),
            uses=data.get("uses", 1),
            condition=Condition(data["condition"]) if data.get("condition") else None,
        ), data)
    if data["kind"] == "weapon":
        weapon = Weapon(data["id"], data["name"], data.get("description", ""),
                        damage=_damage_of(data), attack_bonus=data.get("attack_bonus", 0))
        weapon.reach = data.get("reach", weapon.reach)
        return _with_cell(weapon, data)
    if data["kind"] == "spell":
        values = {key: data[key] for key in ("id", "name", "description", "level", "saving_ability", "save_dc", "duration_rounds")}
        values["damage"] = _damage_of(data, default=None)
        values["condition"] = Condition(data["condition"]) if data.get("condition") else None
        values["range_feet"] = data.get("range_feet", 30)
        return _with_cell(Spell(**values), data)
    return _with_cell(Item(data["id"], data["name"], data.get("description", "")), data)


def _damage_of(data: dict[str, Any], default: Any = "1d8") -> Any:
    """Lee `damage`, y si no esta, el `damage_die`/`damage_bonus` de las partidas antiguas."""
    if data.get("damage") is not None:
        return data["damage"]
    if data.get("damage_die") is None:
        return default
    return Dice(1, data["damage_die"], data.get("damage_bonus", 0))


def _healing_of(data: dict[str, Any]) -> Any:
    if data.get("healing") is not None:
        return data["healing"]
    return Dice(1, data["dice"], data.get("bonus", 0)) if data.get("dice") else Dice(0, 0, data.get("bonus", 0))


def _with_cell(item: Item, data: dict[str, Any]) -> Item:
    item.cell = tuple(data["cell"]) if data.get("cell") else None
    return item


def _quest_to_dict(quest: Quest) -> dict[str, Any]:
    return {"id": quest.id, "name": quest.name, "status": quest.status,
            "fail_event_types": sorted(quest.fail_event_types),
            "objectives": [_objective_to_dict(objective) for objective in quest.objectives.values()],
            "optional_objectives": [_objective_to_dict(objective) for objective in quest.optional_objectives.values()]}


def _quest_from_dict(data: dict[str, Any]) -> Quest:
    objective = lambda item: Objective(item["id"], item["description"], item["event_type"], item.get("target_id"), item.get("completed", False))
    return Quest(data["id"], data["name"], {item["id"]: objective(item) for item in data.get("objectives", [])},
                 {item["id"]: objective(item) for item in data.get("optional_objectives", [])},
                 set(data.get("fail_event_types", [])), data.get("status", "active"))


def _objective_to_dict(objective: Objective) -> dict[str, Any]:
    return {"id": objective.id, "description": objective.description, "event_type": objective.event_type,
            "target_id": objective.target_id, "completed": objective.completed}


def _event_to_dict(event: Event) -> dict[str, Any]:
    return {"type": event.type, "actor_id": event.actor_id, "target_id": event.target_id, "data": event.data,
            "created_at": event.created_at.isoformat()}


def _event_from_dict(data: dict[str, Any]) -> Event:
    created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
    if created_at is None:
        return Event(data["type"], data.get("actor_id"), data.get("target_id"), data.get("data", {}))
    return Event(data["type"], data.get("actor_id"), data.get("target_id"), data.get("data", {}), created_at)
