import pytest

from dnd_engine.game import GameEngine
from dnd_engine.map import Door, Grid, distance_in_cells, distance_in_feet
from dnd_engine.models import AbilityScores, Character, Condition, Enemy, Item, Location, Spell, Weapon, World
from dnd_engine.persistence import load_game, save_game


def make_dungeon(rolls=None, blocked=()):
    """Dos salas de 5x5 unidas por una puerta, con el heroe y un ogro en la primera."""
    world = World("Cripta")
    world.add_location(Location("hall", "Vestibulo", grid=Grid(5, 5, set(blocked))))
    world.add_location(Location("vault", "Camara", grid=Grid(5, 5)))
    world.add_door(Door("hall-vault", "hall", "vault", cell_a=(4, 2), cell_b=(0, 2)))
    engine = GameEngine(world, roller=lambda _low, _high: (rolls or []).pop(0))

    hero = Character("hero", "Hero", max_hp=20, armor_class=12, abilities=AbilityScores(strength=16))
    hero.add_item(Weapon("sword", "Espada", damage_die=8, damage_bonus=2, attack_bonus=3))
    engine.add_character(hero)
    engine.place("hero", "hall", (0, 0))

    ogre = Enemy("ogre", "Ogro", max_hp=20, armor_class=10)
    engine.add_character(ogre)
    engine.place("ogre", "hall", (4, 4))
    return engine


def test_distance_counts_diagonals_as_one_cell():
    assert distance_in_cells((0, 0), (3, 3)) == 3
    assert distance_in_feet((0, 0), (3, 3)) == 15
    assert distance_in_feet((1, 1), (1, 4)) == 15


def test_move_spends_movement_and_publishes_event():
    engine = make_dungeon()
    hero = engine.world.get_character("hero")

    result = engine.move("hero", (2, 2))

    assert hero.position == (2, 2)
    assert result.cost_feet == 10
    assert result.movement_left == 20
    assert hero.resources.movement == 20
    assert engine.events.history[-1].type == "CHARACTER_MOVED"
    assert engine.events.history[-1].data["path"] == [[1, 1], [2, 2]]


def test_move_beyond_the_remaining_movement_is_rejected():
    engine = make_dungeon()
    hero = engine.world.get_character("hero")
    hero.resources.movement = 5

    with pytest.raises(ValueError, match="Se necesitan 10 pies"):
        engine.move("hero", (2, 2))

    assert hero.position == (0, 0)
    assert hero.resources.movement == 5


def test_move_into_a_blocked_cell_is_rejected():
    engine = make_dungeon(blocked=[(1, 1)])

    with pytest.raises(ValueError, match="bloqueada"):
        engine.move("hero", (1, 1))


def test_move_onto_another_character_is_rejected():
    engine = make_dungeon()

    with pytest.raises(ValueError, match="ocupada"):
        engine.move("hero", (4, 4))


def test_path_goes_around_a_wall():
    # Muro vertical en x=1 con un hueco en (1, 4).
    engine = make_dungeon(blocked=[(1, 0), (1, 1), (1, 2), (1, 3)])
    hero = engine.world.get_character("hero")
    hero.speed = 60
    hero.begin_turn()

    result = engine.move("hero", (2, 0))

    # En linea recta serian 10 pies; rodeando el muro por el hueco son 40.
    assert distance_in_feet((0, 0), (2, 0)) == 10
    assert result.cost_feet == 40
    assert (1, 4) in result.path


def test_move_without_a_path_is_rejected():
    engine = make_dungeon(blocked=[(1, 0), (1, 1), (1, 2), (1, 3), (1, 4)])
    hero = engine.world.get_character("hero")
    hero.speed = 200
    hero.begin_turn()

    with pytest.raises(ValueError, match="No hay camino"):
        engine.move("hero", (2, 0))


def test_incapacitated_character_cannot_move():
    engine = make_dungeon()
    engine.world.get_character("hero").conditions.add(Condition.STUNNED)

    with pytest.raises(ValueError, match="no puede moverse"):
        engine.move("hero", (1, 1))


def test_move_in_a_location_without_grid_is_rejected():
    world = World("Taberna")
    world.add_location(Location("tavern", "Taberna"))
    engine = GameEngine(world)
    engine.add_character(Character("hero", "Hero"), "tavern")

    with pytest.raises(ValueError, match="no tiene cuadricula"):
        engine.move("hero", (1, 1))


def test_movement_resets_at_the_start_of_the_turn():
    engine = make_dungeon()
    hero = engine.world.get_character("hero")
    engine.move("hero", (2, 2))
    assert hero.resources.movement == 20

    engine.start_turn("hero")

    assert hero.resources.movement == hero.speed


def test_entering_a_location_without_a_door_is_rejected():
    engine = make_dungeon()
    engine.world.world.add_location(Location("crypt", "Cripta sellada", grid=Grid(3, 3)))

    with pytest.raises(ValueError, match="No hay ninguna puerta"):
        engine.enter_location("hero", "crypt")


def test_entering_through_a_door_places_the_character_at_its_cell():
    engine = make_dungeon()
    hero = engine.world.get_character("hero")

    location = engine.enter_location("hero", "vault")

    assert location.id == "vault"
    assert hero.position == (0, 2)
    assert "hero" in engine.world.world.get_location("vault").occupants
    assert "hero" not in engine.world.world.get_location("hall").occupants
    assert engine.events.history[-1].data["door_id"] == "hall-vault"


def test_a_locked_door_blocks_the_way():
    engine = make_dungeon()
    engine.world.world.get_door("hall-vault").locked = True

    with pytest.raises(ValueError, match="cerrada con llave"):
        engine.enter_location("hero", "vault")


def test_unlocking_a_door_requires_the_key_in_the_inventory():
    engine = make_dungeon()
    door = engine.world.world.get_door("hall-vault")
    door.locked = True
    door.key_id = "brass-key"

    with pytest.raises(ValueError, match="Falta la llave"):
        engine.unlock_door("hall-vault", "hero")

    engine.world.get_character("hero").add_item(Item("brass-key", "Llave de laton"))
    engine.unlock_door("hall-vault", "hero")

    assert door.locked is False
    assert engine.events.history[-1].type == "DOOR_UNLOCKED"
    assert engine.enter_location("hero", "vault").id == "vault"


def test_using_a_door_requires_standing_next_to_it():
    engine = make_dungeon()
    hero = engine.world.get_character("hero")

    with pytest.raises(ValueError, match="junto a la puerta"):
        engine.use_door("hero", "hall-vault")

    hero.position = (4, 1)
    assert engine.use_door("hero", "hall-vault").id == "vault"
    assert hero.position == (0, 2)


def test_entering_an_occupied_door_cell_falls_back_to_a_free_cell():
    engine = make_dungeon()
    engine.add_character(Character("guard", "Guardia"))
    engine.place("guard", "vault", (0, 2))

    engine.enter_location("hero", "vault")

    hero = engine.world.get_character("hero")
    assert hero.position != (0, 2)
    assert engine.world.world.get_location("vault").grid.contains(hero.position)


def test_distance_between_characters():
    engine = make_dungeon()

    assert engine.distance_between("hero", "ogre") == 20

    engine.enter_location("hero", "vault")
    assert engine.distance_between("hero", "ogre") is None


def test_attacking_out_of_reach_is_rejected():
    engine = make_dungeon()

    with pytest.raises(ValueError, match="alcance"):
        engine.attack("hero", "ogre", "sword")


def test_attacking_within_reach_works():
    engine = make_dungeon(rolls=[15, 4])
    engine.world.get_character("hero").position = (3, 4)

    result = engine.attack("hero", "ogre", "sword")

    assert result.hit is True
    assert result.damage == 6


def test_attacking_someone_in_another_location_is_rejected():
    engine = make_dungeon()
    engine.enter_location("hero", "vault")

    with pytest.raises(ValueError, match="no esta en"):
        engine.attack("hero", "ogre", "sword")


def test_spell_range_is_checked_against_the_map():
    engine = make_dungeon(rolls=[5, 6])
    hero = engine.world.get_character("hero")
    hero.spells.append(Spell("bolt", "Rayo", damage_die=8, save_dc=15, range_feet=10))
    hero.spell_slots[1] = 2

    with pytest.raises(ValueError, match="alcance"):
        engine.cast_spell("hero", "ogre", "bolt")

    hero.position = (3, 4)
    result = engine.cast_spell("hero", "ogre", "bolt")
    assert result.damage == 6


def test_save_and_load_preserves_the_map(tmp_path):
    engine = make_dungeon(blocked=[(2, 2)])
    door = engine.world.world.get_door("hall-vault")
    door.locked = True
    door.key_id = "brass-key"
    path = tmp_path / "campaign.json"

    save_game(engine, path)
    loaded = load_game(path)

    hall = loaded.world.world.get_location("hall")
    loaded_door = loaded.world.world.get_door("hall-vault")
    assert hall.grid.blocked == {(2, 2)}
    assert hall.grid.width == 5
    assert loaded_door.locked is True
    assert loaded_door.key_id == "brass-key"
    assert loaded_door.cell_a == (4, 2)
    assert loaded.world.get_character("hero").position == (0, 0)
    assert loaded.world.get_character("hero").get_weapon("sword").reach == 5


def test_old_saves_migrate_connected_locations_into_doors(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(
        '{"world": {"name": "Viejo", "state": {}, "characters": [], "locations": ['
        '{"id": "a", "name": "A", "connected_locations": ["b"], "occupants": []},'
        '{"id": "b", "name": "B", "connected_locations": ["a"], "occupants": []}]}}',
        encoding="utf-8",
    )

    loaded = load_game(path)

    assert len(loaded.world.world.doors) == 1
    assert loaded.world.world.door_between("a", "b") is not None
