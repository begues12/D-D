"""Tests de la fragua de aventuras. Ninguno llama a la API: el cliente se inyecta.

La mitad de arriba prueba la aduana (`validate_scenario`), que es pura y no
necesita modelo; la de abajo, que la fragua le devuelve al modelo el motivo
exacto del rechazo hasta que entrega algo jugable.
"""

import copy

import pytest

from dnd_engine.ai_dm import DungeonMasterError
from dnd_engine.campaign import SCENARIOS, CampaignSetup, PlayerSetup, build_campaign
from dnd_engine.forge import (
    PROPOSE_TOOL,
    SCENARIO_TOOL,
    Pitch,
    ScenarioError,
    ScenarioForge,
    validate_scenario,
)

from test_ai_dm import FakeResponse, ToolUseBlock, fake_client


# -- un plano jugable de referencia -------------------------------------------


def blueprint(**changes):
    base = {
        "name": "El pozo de los nombres",
        "description": "Algo contesta desde el fondo.",
        "intro": "El pozo lleva once anos seco y aun asi alguien pide agua.",
        "start": "brocal",
        "locations": [
            {"id": "brocal", "name": "Brocal del pozo", "description": "Piedra gastada.",
             "grid": {"width": 5, "height": 5, "blocked": [[2, 2]]},
             "items": [{"id": "well-key", "name": "Llave del torno", "cell": [4, 0]},
                       {"id": "well-brew", "name": "Petaca", "cell": [0, 4],
                        "effect": "heal", "healing": "1d6+1"}]},
            {"id": "fondo", "name": "Fondo del pozo", "description": "Barro y huesos.",
             "grid": {"width": 5, "height": 5}},
        ],
        "doors": [{"id": "torno", "a": "brocal", "b": "fondo",
                   "cell_a": [2, 0], "cell_b": [0, 0],
                   "locked": True, "key_id": "well-key"}],
        "npcs": [{"id": "vieja", "name": "La vieja del cubo", "location": "brocal",
                  "cell": [1, 1], "personality": ["sorda"], "knowledge": ["Pide agua."]}],
        "enemies": [{"id": "cosa", "name": "Lo que pide agua", "max_hp": 20,
                     "armor_class": 14, "xp": 200, "location": "fondo", "cell": [4, 4],
                     "abilities": {"strength": 16, "dexterity": 10},
                     "weapon": {"name": "Manos largas", "damage": "1d8+2",
                                "attack_bonus": 5, "reach": 10}}],
        "quest": {"id": "el-pozo", "name": "Callar el pozo", "objectives": [
            {"id": "bajar", "description": "Bajar al fondo",
             "event_type": "PLAYER_ENTERED_LOCATION", "target_id": "fondo"},
            {"id": "matarlo", "description": "Acabar con ello",
             "event_type": "NPC_DIES", "target_id": "cosa"}]},
    }
    base.update(copy.deepcopy(changes))
    return base


def broken(**changes):
    """El plano de referencia con algo roto dentro."""
    return blueprint(**changes)


# -- la aduana ----------------------------------------------------------------


def test_a_sound_blueprint_passes():
    assert validate_scenario(blueprint()) is not None


def test_every_hand_written_scenario_passes_the_same_customs():
    """Lo que se le exige al modelo es lo que ya cumplen los escenarios escritos."""
    for name, data in SCENARIOS.items():
        validate_scenario(data), name


def test_a_forged_blueprint_is_playable_by_the_engine():
    setup = CampaignSetup(players=[PlayerSetup("Nel", "mago")],
                          scenario="el-pozo", blueprint=blueprint())

    engine = build_campaign(setup)

    assert engine.world.world.name == "El pozo de los nombres"
    assert engine.world.get_character("cosa").position == (4, 4)
    assert engine.world.location_of("hero-nel").id == "brocal"
    assert setup.campaign_title == "El pozo de los nombres"


@pytest.mark.parametrize("changes, expected", [
    ({"name": ""}, "Falta 'name'"),
    ({"start": "ninguna"}, "'start' apunta a 'ninguna'"),
    ({"locations": []}, "Falta 'locations'"),
    ({"locations": [{"id": "solo", "name": "Sola"}]}, "entre 2 y 5 ubicaciones"),
    ({"quest": {"id": "q", "name": "Q", "objectives": []}}, "al menos un objetivo"),
])
def test_the_skeleton_is_checked(changes, expected):
    with pytest.raises(ScenarioError, match=expected):
        validate_scenario(broken(**changes))


def test_two_locations_cannot_share_an_id():
    plan = blueprint()
    plan["locations"][1]["id"] = "brocal"
    with pytest.raises(ScenarioError, match="dos ubicaciones con el id 'brocal'"):
        validate_scenario(plan)


def test_a_cell_outside_the_grid_is_rejected():
    plan = blueprint()
    plan["enemies"][0]["cell"] = [5, 0]      # la cuadricula es 5x5: el maximo es 4
    with pytest.raises(ScenarioError, match=r"fuera de la cuadricula 5x5"):
        validate_scenario(plan)


def test_nothing_is_born_inside_a_wall():
    plan = blueprint()
    plan["locations"][0]["items"][0]["cell"] = [2, 2]
    with pytest.raises(ScenarioError, match="dentro de un muro"):
        validate_scenario(plan)


def test_two_creatures_cannot_share_a_cell():
    plan = blueprint()
    plan["npcs"][0]["cell"] = [4, 4]
    plan["npcs"][0]["location"] = "fondo"
    with pytest.raises(ScenarioError, match="nace encima de otro personaje"):
        validate_scenario(plan)


def test_a_door_to_nowhere_is_rejected():
    plan = blueprint()
    plan["doors"][0]["b"] = "sotano"
    with pytest.raises(ScenarioError, match="da a 'sotano', que no existe"):
        validate_scenario(plan)


def test_a_locked_door_needs_a_key_that_exists():
    plan = blueprint()
    plan["doors"][0]["key_id"] = "llave-perdida"
    with pytest.raises(ScenarioError, match="no esta en ninguna parte"):
        validate_scenario(plan)


def test_a_key_behind_its_own_door_makes_the_adventure_impossible():
    """El fallo silencioso mas facil de cometer: la llave al otro lado."""
    plan = blueprint()
    plan["locations"][1]["items"] = plan["locations"][0].pop("items")[:1]
    plan["locations"][0]["items"] = []

    with pytest.raises(ScenarioError, match="No se puede llegar a 'fondo'"):
        validate_scenario(plan)


def test_an_unconnected_location_is_rejected():
    plan = blueprint()
    plan["doors"] = []
    with pytest.raises(ScenarioError, match="ninguna puerta que las conecte"):
        validate_scenario(plan)


def test_an_objective_the_engine_never_publishes_is_rejected():
    plan = blueprint()
    plan["quest"]["objectives"][0]["event_type"] = "PLAYER_IS_HAPPY"
    with pytest.raises(ScenarioError, match="que el motor no publica"):
        validate_scenario(plan)


def test_an_objective_pointing_at_nothing_is_rejected():
    plan = blueprint()
    plan["quest"]["objectives"][1]["target_id"] = "dragon"
    with pytest.raises(ScenarioError, match="apunta a 'dragon'"):
        validate_scenario(plan)


def test_impossible_enemies_are_rejected():
    plan = blueprint()
    plan["enemies"][0]["armor_class"] = 40
    with pytest.raises(ScenarioError, match="'armor_class' entre 5 y 25"):
        validate_scenario(plan)


def test_a_weapon_with_nonsense_damage_is_rejected():
    plan = blueprint()
    plan["enemies"][0]["weapon"]["damage"] = "un mordisco"
    with pytest.raises(ScenarioError, match="La tirada de el arma"):
        validate_scenario(plan)


def test_a_potion_that_heals_nothing_readable_is_rejected():
    plan = blueprint()
    plan["locations"][0]["items"][1]["healing"] = "bastante"
    with pytest.raises(ScenarioError, match="La tirada de la curacion"):
        validate_scenario(plan)


def test_enemies_cannot_steal_a_player_id():
    plan = blueprint()
    plan["enemies"][0]["id"] = "hero-nel"
    with pytest.raises(ScenarioError, match="reservado a los jugadores"):
        validate_scenario(plan)


# -- la fragua ----------------------------------------------------------------


def proposals(*names):
    return FakeResponse([ToolUseBlock(
        PROPOSE_TOOL["name"],
        {"adventures": [{"name": one, "description": f"{one}, en una frase.",
                         "intro": f"Gancho de {one}."} for one in names]})])


def built(plan):
    return FakeResponse([ToolUseBlock(SCENARIO_TOOL["name"], plan)])


def forge(*responses):
    return ScenarioForge(fake_client(*responses))


def test_proposing_returns_pitches_with_unique_ids():
    maker = forge(proposals("El pozo", "La torre", "El pozo"))

    pitches = maker.propose(3, hint="algo con agua", party_size=2)

    assert [one.name for one in pitches] == ["El pozo", "La torre", "El pozo"]
    assert [one.id for one in pitches] == ["el-pozo", "la-torre", "el-pozo-2"]
    assert pitches[0].description == "El pozo, en una frase."
    message = maker.client.messages.calls[0]["messages"][0]["content"]
    assert "algo con agua" in message
    assert "2 jugador(es)" in message


def test_proposing_can_be_told_what_not_to_repeat():
    maker = forge(proposals("La torre"))

    maker.propose(1, avoid=("El pozo",))

    assert "El pozo" in maker.client.messages.calls[0]["messages"][0]["content"]


def test_proposing_forces_the_tool():
    maker = forge(proposals("El pozo"))

    maker.propose(1)

    call = maker.client.messages.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": PROPOSE_TOOL["name"]}


def test_a_model_that_proposes_nothing_is_an_error():
    maker = forge(FakeResponse([ToolUseBlock(PROPOSE_TOOL["name"], {"adventures": []})]))

    with pytest.raises(DungeonMasterError, match="no propuso ninguna aventura"):
        maker.propose(3)


def test_building_returns_the_validated_blueprint():
    maker = forge(built(blueprint()))

    plan = maker.build(Pitch("el-pozo", "El pozo de los nombres", "Algo contesta."))

    assert plan["start"] == "brocal"
    assert build_campaign(CampaignSetup(scenario="el-pozo", blueprint=plan)) is not None


def test_a_broken_blueprint_goes_back_to_the_model_with_the_reason():
    """El rechazo no se tira: vuelve como resultado de su propia herramienta."""
    plan = blueprint()
    plan["enemies"][0]["cell"] = [9, 9]
    maker = forge(built(plan), built(blueprint()))

    maker.build(Pitch("el-pozo", "El pozo", "Algo contesta."))

    second = maker.client.messages.calls[1]["messages"]
    result = second[-1]["content"][0]
    assert result["type"] == "tool_result" and result["is_error"] is True
    assert "fuera de la cuadricula" in result["content"]
    assert len(maker.client.messages.calls) == 2


def test_the_forge_gives_up_with_the_last_reason():
    plan = blueprint()
    plan["start"] = "ninguna"
    maker = forge(built(plan), built(plan))

    with pytest.raises(DungeonMasterError, match="no consiguio un escenario jugable"):
        maker.build(Pitch("el-pozo", "El pozo", "Algo contesta."), attempts=2)


def test_a_model_that_ignores_the_tool_is_an_error():
    maker = forge(FakeResponse([]))

    with pytest.raises(DungeonMasterError, match="no uso la herramienta"):
        maker.build(Pitch("el-pozo", "El pozo", "Algo contesta."))


def test_the_pitch_intro_survives_if_the_model_forgets_it():
    plan = blueprint()
    del plan["intro"]
    maker = forge(built(plan))

    result = maker.build(Pitch("el-pozo", "El pozo", "Algo contesta.", "Un gancho."))

    assert result["intro"] == "Un gancho."


def test_forging_everything_builds_one_adventure_per_proposal():
    maker = forge(proposals("El pozo", "La torre"), built(blueprint()), built(blueprint()))

    forged = maker.forge(2)

    assert [pitch.name for pitch, _ in forged] == ["El pozo", "La torre"]
    assert len(maker.client.messages.calls) == 3
