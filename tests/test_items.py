import io

import pytest

from dnd_engine.console import Console
from dnd_engine.game import GameEngine
from dnd_engine.map import Door, Grid
from dnd_engine.models import (
    Character, Condition, Consumable, Item, ItemEffect, Location, Weapon, World,
)
from dnd_engine.persistence import load_game, save_game


def make_game():
    world = World("Prueba")
    world.add_location(Location(
        "hall", "Vestibulo", grid=Grid(5, 5),
        items=[Item("key", "Llave de hierro", "Oxidada.", (4, 4)),
               Item("coin", "Moneda", cell=(0, 1))],
    ))
    world.add_location(Location(
        "cellar", "Bodega",
        items=[Item("rag", "Trapo")],  # sin cuadricula: sin casilla
    ))
    world.add_door(Door("iron-door", "hall", "cellar", cell_a=(0, 4),
                        locked=True, key_id="key"))
    engine = GameEngine(world, roller=lambda _low, high: min(high, 15))
    hero = Character("hero", "Aldric", max_hp=20, armor_class=12)
    hero.add_item(Weapon("sword", "Espada", damage_die=8))
    engine.add_character(hero)
    engine.place("hero", "hall", (0, 0))
    return engine


def test_taking_an_item_moves_it_into_the_inventory():
    engine = make_game()

    item = engine.take_item("hero", "coin")

    hero = engine.world.get_character("hero")
    assert item.id == "coin"
    assert item.cell is None  # deja de estar en el suelo
    assert "coin" in {one.id for one in hero.inventory}
    assert "coin" not in {one.id for one in engine.world.items_in("hall")}
    assert engine.events.history[-1].type == "ITEM_TAKEN"


def test_outside_combat_there_is_no_economy_to_spend():
    engine = make_game()
    engine.move("hero", (3, 3))

    # Tres manipulaciones seguidas sin ningun turno de por medio.
    engine.take_item("hero", "key")
    engine.drop_item("hero", "key")
    engine.take_item("hero", "key")

    hero = engine.world.get_character("hero")
    assert hero.resources.object_interaction is True
    assert "key" in {one.id for one in hero.inventory}


def test_in_combat_taking_costs_the_interaction_but_not_the_action():
    engine = make_game()
    engine.begin_encounter(["hero"])
    engine.next_turn()

    engine.take_item("hero", "coin")

    hero = engine.world.get_character("hero")
    assert hero.resources.object_interaction is False
    assert hero.resources.action is True
    assert hero.resources.movement == hero.speed


def test_only_one_object_interaction_per_combat_turn():
    engine = make_game()
    engine.begin_encounter(["hero"])
    engine.next_turn()
    engine.take_item("hero", "coin")

    with pytest.raises(ValueError, match="un objeto este turno"):
        engine.drop_item("hero", "coin")

    engine.next_turn()
    engine.drop_item("hero", "coin")
    assert "coin" in {one.id for one in engine.world.items_in("hall")}


def test_taking_something_far_away_is_rejected():
    engine = make_game()  # la llave esta en (4, 4) y el heroe en (0, 0)

    with pytest.raises(ValueError, match="hay que estar al lado"):
        engine.take_item("hero", "key")


def test_walking_up_to_it_makes_it_reachable():
    engine = make_game()
    engine.move("hero", (3, 3))

    assert engine.take_item("hero", "key").id == "key"


def test_a_location_without_a_grid_has_no_distance_rule():
    engine = make_game()
    engine.world.place("hero", "cellar")

    assert engine.take_item("hero", "rag").id == "rag"


def test_taking_something_that_is_not_there_is_rejected():
    engine = make_game()

    with pytest.raises(ValueError, match="no hay ningun 'corona'"):
        engine.take_item("hero", "corona")


def test_dropping_what_you_do_not_carry_is_rejected():
    engine = make_game()

    with pytest.raises(ValueError, match="No llevas ningun 'corona'"):
        engine.drop_item("hero", "corona")


def test_dropped_items_land_on_your_cell():
    engine = make_game()
    engine.move("hero", (2, 2))

    item = engine.drop_item("hero", "sword")

    assert item.cell == (2, 2)
    assert "sword" in {one.id for one in engine.world.items_in("hall")}
    assert engine.events.history[-1].type == "ITEM_DROPPED"


def test_an_incapacitated_character_cannot_handle_objects():
    engine = make_game()
    engine.world.get_character("hero").conditions.add(Condition.STUNNED)

    with pytest.raises(ValueError, match="no puede coger"):
        engine.take_item("hero", "coin")
    with pytest.raises(ValueError, match="no puede soltar"):
        engine.drop_item("hero", "sword")


def test_a_found_key_opens_the_door_it_belongs_to():
    engine = make_game()
    engine.move("hero", (3, 3))
    engine.take_item("hero", "key")

    engine.unlock_door("iron-door", "hero")

    assert engine.world.world.get_door("iron-door").locked is False


def test_the_door_stays_shut_while_the_key_is_on_the_floor():
    engine = make_game()

    with pytest.raises(ValueError, match="Falta la llave"):
        engine.unlock_door("iron-door", "hero")


def test_floor_items_survive_save_and_load(tmp_path):
    engine = make_game()
    engine.move("hero", (2, 2))
    engine.drop_item("hero", "sword")
    path = tmp_path / "campana.json"

    save_game(engine, path)
    loaded = load_game(path)

    floor = {one.id: one for one in loaded.world.items_in("hall")}
    assert floor["key"].cell == (4, 4)
    assert floor["key"].description == "Oxidada."
    assert isinstance(floor["sword"], Weapon)
    assert floor["sword"].cell == (2, 2)
    assert loaded.world.items_in("cellar")[0].cell is None


# -- consola ------------------------------------------------------------------


def console_of(engine):
    return Console(engine, "hero", io.StringIO(), io.StringIO())


def test_look_and_map_show_what_is_on_the_floor():
    console = console_of(make_game())

    console.handle("mirar")
    console.handle("mapa")

    text = console.stream_out.getvalue()
    assert "en el suelo: Llave de hierro [key], en (4, 4)" in text
    assert "*" in text
    assert "* objeto" in text


def test_taking_and_dropping_from_the_console():
    console = console_of(make_game())

    console.handle("coger coin")
    console.handle("soltar coin")

    text = console.stream_out.getvalue()
    assert "Aldric coge Moneda." in text
    assert "Aldric deja Moneda en el suelo." in text


def test_the_console_enforces_the_economy_once_combat_starts():
    console = console_of(make_game())
    console.engine.begin_encounter(["hero"])
    console.engine.next_turn()

    console.handle("coger coin")
    console.handle("soltar coin")

    assert "[!] Ya has manipulado un objeto este turno." in console.stream_out.getvalue()


# -- consumibles --------------------------------------------------------------


def potion(item_id="potion", **overrides):
    values = {"effect": ItemEffect.HEAL, "dice": 8, "bonus": 2}
    values.update(overrides)
    return Consumable(item_id, "Pocion de curacion", **values)


def wounded_game():
    engine = make_game()
    hero = engine.world.get_character("hero")
    hero.hp = 5
    hero.add_item(potion())
    ally = Character("ally", "Nel", max_hp=15, armor_class=12)
    engine.add_character(ally)
    engine.place("ally", "hall", (1, 0))
    return engine


def test_drinking_a_potion_heals_and_spends_it():
    engine = wounded_game()

    result = engine.use_item("hero", "potion")

    hero = engine.world.get_character("hero")
    assert result.healed == 10  # d8=8 con el roller fijo, +2
    assert hero.hp == 15
    assert result.spent is True
    assert "potion" not in {one.id for one in hero.inventory}
    assert [event.type for event in engine.events.history[-2:]] == ["HEALED", "ITEM_USED"]


def test_in_combat_a_potion_costs_the_action_not_the_interaction():
    engine = wounded_game()
    engine.begin_encounter(["hero"])
    engine.next_turn()

    engine.use_item("hero", "potion")

    hero = engine.world.get_character("hero")
    assert hero.resources.action is False
    assert hero.resources.object_interaction is True


def test_a_potion_with_several_uses_is_not_spent_at_once():
    engine = wounded_game()
    hero = engine.world.get_character("hero")
    hero.inventory.remove(hero.get_item("potion"))
    hero.add_item(potion("balm", uses=2))

    result = engine.use_item("hero", "balm")

    assert result.spent is False
    assert result.uses_left == 1
    assert hero.get_item("balm").uses == 1


def test_a_potion_can_be_given_to_someone_next_to_you():
    engine = wounded_game()
    engine.world.get_character("ally").hp = 3

    result = engine.use_item("hero", "potion", "ally")

    assert result.target_id == "ally"
    assert engine.world.get_character("ally").hp == 13
    assert engine.world.get_character("hero").hp == 5  # el que la usa no se cura


def test_you_cannot_reach_someone_across_the_room():
    engine = wounded_game()
    engine.world.get_character("ally").position = (4, 4)

    with pytest.raises(ValueError, match="alcance"):
        engine.use_item("hero", "potion", "ally")


def test_a_potion_brings_a_downed_ally_back():
    engine = wounded_game()
    ally = engine.world.get_character("ally")
    ally.hp = 0
    ally.conditions.add(Condition.UNCONSCIOUS)
    ally.death_saves.failures = 2

    engine.use_item("hero", "potion", "ally")

    assert ally.hp == 10
    assert Condition.UNCONSCIOUS not in ally.conditions
    assert ally.death_saves.failures == 0
    assert "CHARACTER_REVIVED" in [event.type for event in engine.events.history]


def test_a_potion_is_not_wasted_on_someone_at_full_health():
    engine = wounded_game()
    engine.world.get_character("hero").hp = 20  # el maximo

    with pytest.raises(ValueError, match="puntos de golpe completos"):
        engine.use_item("hero", "potion")

    assert engine.world.get_character("hero").get_item("potion").uses == 1


def test_an_exhausted_potion_cannot_be_used():
    engine = wounded_game()
    hero = engine.world.get_character("hero")
    hero.get_item("potion").uses = 0

    with pytest.raises(ValueError, match="agotado"):
        engine.use_item("hero", "potion")


def test_you_cannot_use_two_things_in_one_combat_turn():
    engine = wounded_game()
    hero = engine.world.get_character("hero")
    hero.add_item(potion("balm"))
    engine.begin_encounter(["hero"])
    engine.next_turn()

    engine.use_item("hero", "potion")

    with pytest.raises(ValueError, match="usado tu accion"):
        engine.use_item("hero", "balm")


def test_ordinary_items_are_not_usable():
    engine = wounded_game()

    with pytest.raises(ValueError, match="no se puede usar"):
        engine.use_item("hero", "sword")


def test_an_antidote_removes_the_condition_it_cures():
    engine = wounded_game()
    hero = engine.world.get_character("hero")
    hero.add_item(potion("antidote", effect=ItemEffect.CURE, dice=0, bonus=0,
                         condition=Condition.POISONED))
    hero.conditions.add(Condition.POISONED)
    hero.condition_durations[Condition.POISONED] = 3

    result = engine.use_item("hero", "antidote")

    assert result.cured == "poisoned"
    assert Condition.POISONED not in hero.conditions
    assert hero.condition_durations == {}
    assert engine.events.history[-2].type == "CONDITION_CURED"


def test_an_antidote_is_not_wasted_on_someone_who_is_fine():
    engine = wounded_game()
    hero = engine.world.get_character("hero")
    hero.add_item(potion("antidote", effect=ItemEffect.CURE, dice=0, bonus=0,
                         condition=Condition.POISONED))

    with pytest.raises(ValueError, match="no sufre el estado"):
        engine.use_item("hero", "antidote")

    assert hero.get_item("antidote").uses == 1
    assert hero.resources.action is True


def test_consumables_survive_save_and_load(tmp_path):
    engine = wounded_game()
    engine.world.get_character("hero").add_item(
        potion("balm", uses=2, effect=ItemEffect.CURE, dice=0,
               condition=Condition.BLINDED))
    path = tmp_path / "campana.json"

    save_game(engine, path)
    balm = load_game(path).world.get_character("hero").get_item("balm")

    assert isinstance(balm, Consumable)
    assert balm.uses == 2
    assert balm.effect is ItemEffect.CURE
    assert balm.condition is Condition.BLINDED


def test_using_a_potion_from_the_console():
    engine = wounded_game()
    console = console_of(engine)

    console.handle("usar potion")
    console.handle("inventario")

    text = console.stream_out.getvalue()
    assert "usa Pocion de curacion: recupera 10 puntos de golpe. (se agota)" in text
    assert "Espada [sword]" in text  # el inventario se pinta
    assert "potion" not in {
        one.id for one in engine.world.get_character("hero").inventory}
