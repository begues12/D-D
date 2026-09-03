import io

import pytest

from dnd_engine import tactics
from dnd_engine.actions import ACTIONS, Intent, action_schema, execute
from dnd_engine.console import Console
from dnd_engine.game import GameEngine
from dnd_engine.map import Door, Grid
from dnd_engine.models import (
    AbilityScores, Character, Condition, Enemy, Item, Location, Weapon, World,
)


def make_game(rolls=None):
    """Sala de 5x5 con el heroe en (0, 0), un goblin en (4, 4) y una despensa cerrada."""
    world = World("Prueba")
    world.add_location(Location("hall", "Vestibulo", grid=Grid(5, 5)))
    world.add_location(Location("pantry", "Despensa", grid=Grid(3, 3)))
    world.add_door(Door("pantry-door", "hall", "pantry", cell_a=(0, 4), cell_b=(0, 0),
                        locked=True, key_id="key"))
    engine = GameEngine(world, roller=lambda _low, _high: (rolls or []).pop(0))

    hero = Character("hero", "Hero", max_hp=20, armor_class=12,
                     abilities=AbilityScores(strength=16))
    hero.add_item(Weapon("sword", "Espada", damage_die=8, damage_bonus=2, attack_bonus=3))
    hero.add_item(Item("key", "Llave"))
    engine.add_character(hero)
    engine.place("hero", "hall", (0, 0))

    goblin = Enemy("goblin", "Goblin", max_hp=8, armor_class=10, experience_reward=50)
    goblin.add_item(Weapon("dagger", "Daga", damage_die=4, damage_bonus=1, attack_bonus=3))
    engine.add_character(goblin)
    engine.place("goblin", "hall", (4, 4))
    return engine


def make_console(rolls=None, script=""):
    engine = make_game(rolls)
    return Console(engine, "hero", io.StringIO(script), io.StringIO())


def output(console):
    return console.stream_out.getvalue()


# -- intenciones -------------------------------------------------------------


def test_unknown_action_is_rejected():
    engine = make_game()

    with pytest.raises(ValueError, match="Accion desconocida"):
        execute(engine, Intent("teleport", {}, "hero"))


def test_missing_parameter_is_rejected():
    engine = make_game()

    with pytest.raises(ValueError, match="necesita el parametro 'y'"):
        execute(engine, Intent("move", {"x": 1}, "hero"))


def test_unexpected_parameter_is_rejected():
    engine = make_game()

    with pytest.raises(ValueError, match="no acepta el parametro 'speed'"):
        execute(engine, Intent("move", {"x": 1, "y": 1, "speed": 9}, "hero"))


def test_non_numeric_parameter_is_rejected():
    engine = make_game()

    with pytest.raises(ValueError, match="debe ser un numero entero"):
        execute(engine, Intent("move", {"x": "izquierda", "y": 1}, "hero"))


def test_action_without_actor_is_rejected():
    engine = make_game()

    with pytest.raises(ValueError, match="necesita un personaje"):
        execute(engine, Intent("move", {"x": 1, "y": 1}))


def test_move_intent_moves_the_character():
    engine = make_game()

    result = execute(engine, Intent("move", {"x": "2", "y": "2"}, "hero"))

    assert engine.world.get_character("hero").position == (2, 2)
    assert result.data["cost_feet"] == 10


def test_approach_intent_stops_on_a_free_adjacent_cell():
    engine = make_game()

    result = execute(engine, Intent("approach", {"target": "goblin"}, "hero"))

    hero = engine.world.get_character("hero")
    goblin = engine.world.get_character("goblin")
    assert hero.position != goblin.position
    assert engine.distance_between("hero", "goblin") == 5
    assert result.data["destination"] == hero.position


def test_direct_move_still_rejects_an_occupied_cell():
    engine = make_game()

    with pytest.raises(ValueError, match="ya esta ocupada"):
        execute(engine, Intent("move", {"x": 4, "y": 4}, "hero"))


def test_attack_intent_uses_the_first_weapon_by_default():
    engine = make_game([15, 4])
    engine.world.get_character("hero").position = (3, 4)

    result = execute(engine, Intent("attack", {"target": "goblin"}, "hero"))

    assert result.data["hit"] is True
    assert "Espada" in result.summary


def test_action_schema_documents_every_action():
    schema = {entry["action"] for entry in action_schema()}

    assert schema == set(ACTIONS)
    move = next(entry for entry in action_schema() if entry["action"] == "move")
    assert [parameter["name"] for parameter in move["parameters"]] == ["x", "y"]
    assert all(parameter["required"] for parameter in move["parameters"])


# -- consola ------------------------------------------------------------------


def test_unknown_command_does_not_stop_the_loop():
    console = make_console()

    assert console.handle("bailar") is True
    assert "No conozco 'bailar'" in output(console)


def test_rule_errors_are_reported_without_crashing():
    console = make_console()

    assert console.handle("mover 99 99") is True
    assert "fuera de 'hall'" in output(console)


def test_missing_arguments_are_reported():
    console = make_console()

    assert console.handle("mover 1") is True
    assert "Faltan argumentos" in output(console)


def test_map_command_draws_characters_and_obstacles():
    console = make_console()
    console.engine.world.world.get_location("hall").grid.blocked.add((2, 2))

    console.handle("mapa")

    lines = output(console).splitlines()
    assert lines[1].strip().startswith("0 @")
    assert "#" in output(console)
    assert "G" in output(console)  # la inicial del nombre, "Goblin"


def test_look_lists_occupants_doors_and_distance():
    console = make_console()

    console.handle("mirar")

    text = output(console)
    assert "Goblin (goblin)" in text
    assert "a 20 pies" in text
    assert "cerrada con llave" in text


def test_console_runs_a_whole_scripted_session():
    console = make_console(script="mirar\nmover 2 2\nestado\nsalir\n")

    console.run()

    text = output(console)
    assert console.engine.world.get_character("hero").position == (2, 2)
    assert "se mueve a (2, 2)" in text
    assert "Hasta la proxima" in text


def test_unlocking_and_crossing_a_door_from_the_console():
    console = make_console()

    console.handle("abrir pantry-door")
    console.handle("mover 0 4")
    console.handle("puerta pantry-door")

    assert console.engine.world.location_of("hero").id == "pantry"
    assert "Despensa" in output(console)


def test_console_reports_consequences_of_an_action():
    console = make_console([20, 4, 4])
    console.engine.world.get_character("hero").position = (3, 4)

    console.handle("atacar goblin")

    text = output(console)
    assert "Goblin cae derrotado." in text
    assert "gana 50 de experiencia" in text


def test_enemy_turns_play_themselves_but_do_not_steal_control():
    # Los participantes se ordenan por id: primero tira el goblin, luego el heroe.
    console = make_console([20, 1, 15, 3])

    console.handle("combate")

    text = output(console)
    assert "turno de Goblin" in text
    assert "Goblin se mueve" in text
    # El goblin actua, pero el jugador sigue llevando al heroe.
    assert console.actor_id == "hero"


def test_control_stays_with_the_player_when_the_fight_is_decided():
    # Iniciativa 20/1, luego el ataque del goblin (d20=15) y su dano (d4=2).
    console = make_console([20, 1, 15, 2])
    hero = console.engine.world.get_character("hero")
    hero.position = (3, 4)
    console.handle("combate hero goblin")
    assert console.actor_id == "hero"

    # El heroe llega a 0 y el golpe del goblin lo tumba: ya no hay dos bandos.
    hero.hp = 0
    console.handle("turno")

    assert Condition.UNCONSCIOUS in hero.conditions
    assert "Ya no quedan dos bandos" in output(console)
    assert console.actor_id == "hero"


def test_save_and_load_from_the_console(tmp_path):
    path = tmp_path / "partida.json"
    console = make_console()
    console.handle("mover 2 2")

    console.handle(f"guardar {path}")
    console.handle("mover 3 3")
    console.handle(f"cargar {path}")

    assert console.engine.world.get_character("hero").position == (2, 2)
    assert console.actor_id == "hero"


def test_quests_and_events_commands_render():
    console = make_console()

    console.handle("misiones")
    console.handle("eventos 5")
    console.handle("inventario")
    console.handle("ayuda")

    text = output(console)
    assert "(sin misiones)" in text
    assert "Espada [sword]" in text
    assert "alcance 5" in text


# -- tactica ------------------------------------------------------------------


def test_tactic_approaches_and_attacks():
    engine = make_game([15, 3])
    engine.start_turn("goblin")

    results = tactics.take_turn(engine, "goblin")

    goblin = engine.world.get_character("goblin")
    assert len(results) == 2
    assert goblin.position != (4, 4)
    assert engine.distance_between("goblin", "hero") <= 5


def test_tactic_does_nothing_when_incapacitated():
    engine = make_game()
    engine.world.get_character("goblin").conditions.add(Condition.STUNNED)

    assert tactics.take_turn(engine, "goblin") == []


def test_tactic_targets_the_other_side_only():
    engine = make_game()
    hero = engine.world.get_character("hero")
    goblin = engine.world.get_character("goblin")

    assert tactics.is_hostile(goblin, hero) is True
    assert tactics.is_hostile(hero, goblin) is True
    assert tactics.is_hostile(hero, hero) is False
