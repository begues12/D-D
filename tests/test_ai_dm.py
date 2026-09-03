"""Tests del DM con IA. Ninguno llama a la API: el cliente se inyecta."""

import io
from dataclasses import dataclass, field
from typing import Any

import pytest

from dnd_engine.actions import ACTIONS
from dnd_engine.ai_dm import (
    MAX_INTENTS,
    NO_ACTION,
    DungeonMaster,
    DungeonMasterError,
    build_tools,
    describe_state,
)
from dnd_engine.campaign import CampaignSetup, build_campaign
from dnd_engine.console import Console
from dnd_engine.game import GameEngine
from dnd_engine.map import Door, Grid
from dnd_engine.models import AbilityScores, Character, Enemy, Item, Location, Spell, Weapon, World


# -- dobles del SDK -----------------------------------------------------------


@dataclass
class ToolUseBlock:
    name: str
    input: dict[str, Any]
    type: str = "tool_use"
    id: str = "toolu_test"


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeResponse:
    content: list[Any]
    stop_reason: str = "end_turn"


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **parameters):
        self.calls.append(parameters)
        if not self.responses:
            raise AssertionError("El DM hizo mas llamadas de las previstas.")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@dataclass
class FakeClient:
    messages: FakeMessages = field(default_factory=lambda: FakeMessages([]))


def fake_client(*responses):
    return FakeClient(FakeMessages(responses))


def tool_call(name, **parameters):
    return FakeResponse([ToolUseBlock(name, parameters)])


def narration(text):
    return FakeResponse([TextBlock(text)])


# -- escenario ----------------------------------------------------------------


def make_game():
    world = World("Prueba")
    world.add_location(Location("cellar", "Bodega", grid=Grid(6, 4, {(2, 1)})))
    world.add_location(Location("vault", "Camara", grid=Grid(3, 3)))
    world.add_door(Door("iron-door", "cellar", "vault", cell_a=(5, 0), cell_b=(0, 0),
                        locked=True, key_id="iron-key"))
    # Dados deterministas: 15 en el d20, el maximo en dados menores.
    engine = GameEngine(world, roller=lambda _low, high: min(high, 15))

    hero = Character("hero", "Aldric", max_hp=18, armor_class=14,
                     abilities=AbilityScores(strength=16))
    hero.add_item(Weapon("longsword", "Espada larga", damage_die=8, damage_bonus=3,
                         attack_bonus=5))
    hero.add_item(Item("iron-key", "Llave de hierro"))
    hero.spells.append(Spell("firebolt", "Rayo de fuego", damage_die=6, range_feet=60))
    hero.spell_slots[1] = 2
    engine.add_character(hero)
    engine.place("hero", "cellar", (0, 0))

    goblin = Enemy("goblin-1", "Goblin", max_hp=9, armor_class=13, experience_reward=50)
    goblin.add_item(Weapon("scimitar", "Cimitarra", damage_die=6, damage_bonus=1))
    engine.add_character(goblin)
    engine.place("goblin-1", "cellar", (5, 3))
    return engine


# -- catalogo de herramientas -------------------------------------------------


def test_tools_cover_every_action_plus_no_action():
    names = {tool["name"] for tool in build_tools()}

    assert names == set(ACTIONS) | {NO_ACTION}


def test_tool_schemas_are_strict():
    for tool in build_tools():
        schema = tool["input_schema"]
        assert tool["strict"] is True
        assert schema["additionalProperties"] is False
        # El modo estricto exige declarar todas las propiedades como requeridas.
        assert set(schema["required"]) == set(schema["properties"])


def test_optional_parameters_are_declared_nullable():
    attack = next(tool for tool in build_tools() if tool["name"] == "attack")
    properties = attack["input_schema"]["properties"]

    assert properties["target"]["type"] == "string"
    assert properties["weapon"]["type"] == ["string", "null"]


def test_integer_parameters_keep_their_type():
    move = next(tool for tool in build_tools() if tool["name"] == "move")

    assert move["input_schema"]["properties"]["x"]["type"] == "integer"


# -- descripcion del estado ---------------------------------------------------


def test_state_lists_the_identifiers_the_model_must_use():
    state = describe_state(make_game(), "hero")

    assert "Bodega (cellar) - cuadricula 6x4" in state
    assert "Aldric (hero), 18/18 HP" in state
    assert "longsword" in state and "alcance 5" in state
    assert "firebolt" in state and "alcance 60" in state
    assert "iron-key" in state
    assert "goblin-1" in state and "a 25 pies" in state
    assert "iron-door -> vault, cerrada con llave, en la casilla (5, 0)" in state
    assert "CASILLAS BLOQUEADAS: (2, 1)" in state
    assert "COMBATE: no hay ninguno activo" in state


def test_state_reports_the_active_encounter():
    engine = make_game()
    engine.begin_encounter(["hero", "goblin-1"])
    engine.next_turn()

    assert "COMBATE: ronda 1, turno de" in describe_state(engine, "hero")


# -- ciclo interpretar / ejecutar / narrar ------------------------------------


def test_play_executes_the_chosen_action_and_narrates_it():
    engine = make_game()
    engine.world.get_character("hero").position = (4, 3)
    client = fake_client(
        tool_call("attack", target="goblin-1", weapon=None),
        narration("Tu espada muerde el hombro del goblin."),
    )

    turn = DungeonMaster(client).play(engine, "hero", "ataco al goblin con la espada")

    assert turn.intent.action == "attack"
    assert turn.intent.parameters == {"target": "goblin-1"}  # el null se descarta
    assert turn.intent.actor_id == "hero"
    assert turn.error is None
    assert turn.acted is True
    assert engine.world.get_character("goblin-1").hp < 9
    assert turn.narration == "Tu espada muerde el hombro del goblin."
    assert any(event.type == "PLAYER_ATTACK" for event in turn.events)


def test_play_reports_a_rule_rejection_without_touching_the_world():
    engine = make_game()  # el goblin esta a 25 pies y la espada alcanza 5
    client = fake_client(
        tool_call("attack", target="goblin-1", weapon="longsword"),
        narration("Esta demasiado lejos para alcanzarlo."),
    )

    turn = DungeonMaster(client).play(engine, "hero", "ataco al goblin")

    assert turn.acted is False
    assert "alcance" in turn.error
    assert engine.world.get_character("goblin-1").hp == 9
    assert engine.world.get_character("hero").resources.action is True


def test_no_action_skips_the_engine_entirely():
    engine = make_game()
    client = fake_client(
        tool_call(NO_ACTION, reason="Es una pregunta, no una accion."),
        narration("La bodega huele a moho."),
    )

    turn = DungeonMaster(client).play(engine, "hero", "que hay en la bodega?")

    assert turn.intent.action == NO_ACTION
    assert turn.acted is False
    assert turn.error is None
    assert turn.events == ()


def test_movement_intent_coerces_its_numbers():
    engine = make_game()
    client = fake_client(
        tool_call("move", x=2, y=2),
        narration("Avanzas entre los barriles."),
    )

    turn = DungeonMaster(client).play(engine, "hero", "me acerco al centro")

    assert engine.world.get_character("hero").position == (2, 2)
    assert turn.result.data["cost_feet"] == 10


def test_an_invented_target_is_rejected_by_the_engine():
    engine = make_game()
    client = fake_client(
        tool_call("attack", target="dragon", weapon=None),
        narration("No hay ningun dragon aqui."),
    )

    turn = DungeonMaster(client).play(engine, "hero", "ataco al dragon")

    assert turn.acted is False
    assert "dragon" in turn.error


# -- forma de las peticiones --------------------------------------------------


def test_interpretation_forces_at_least_one_tool_call():
    client = fake_client(tool_call(NO_ACTION, reason="x"))
    DungeonMaster(client).interpret(make_game(), "hero", "hola")

    request = client.messages.calls[0]
    # Sin disable_parallel: una frase puede traer una secuencia de acciones.
    assert request["tool_choice"] == {"type": "any"}
    assert request["model"] == "claude-opus-5"
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["output_config"] == {"effort": "low"}


def test_narration_is_asked_without_tools():
    engine = make_game()
    client = fake_client(tool_call(NO_ACTION, reason="x"), narration("Nada ocurre."))
    DungeonMaster(client).play(engine, "hero", "hola")

    narration_request = client.messages.calls[1]
    assert "tools" not in narration_request
    assert "tool_choice" not in narration_request


def test_the_narrator_receives_the_real_numbers():
    engine = make_game()
    engine.world.get_character("hero").position = (4, 3)
    client = fake_client(
        tool_call("attack", target="goblin-1", weapon=None),
        narration("..."),
    )
    DungeonMaster(client).play(engine, "hero", "ataco")

    prompt = client.messages.calls[1]["messages"][0]["content"]
    assert "RESULTADO REAL:" in prompt
    assert "PLAYER_ATTACK" in prompt
    assert "prohibido inventar" in client.messages.calls[1]["system"][0]["text"]


def test_a_rejection_reaches_the_narrator_verbatim():
    engine = make_game()
    client = fake_client(tool_call("attack", target="goblin-1", weapon=None), narration("..."))
    DungeonMaster(client).play(engine, "hero", "ataco")

    prompt = client.messages.calls[1]["messages"][0]["content"]
    assert "LAS REGLAS RECHAZAN LA ACCION" in prompt
    assert "alcance" in prompt


# -- fallos -------------------------------------------------------------------


def test_a_response_without_a_tool_call_is_an_error():
    client = fake_client(FakeResponse([TextBlock("no se")], stop_reason="end_turn"))

    with pytest.raises(DungeonMasterError, match="no eligio ninguna accion"):
        DungeonMaster(client).interpret(make_game(), "hero", "hola")


def test_a_refusal_is_an_error():
    client = fake_client(FakeResponse([], stop_reason="refusal"))

    with pytest.raises(DungeonMasterError, match="declino"):
        DungeonMaster(client).interpret(make_game(), "hero", "hola")


def test_console_keeps_playing_when_the_dm_is_unavailable():
    console = Console(make_game(), "hero", io.StringIO(), io.StringIO())
    console._dungeon_master = _BrokenDungeonMaster()

    assert console.handle("dm ataco al goblin") is True
    assert "DM no disponible" in console.stream_out.getvalue()


def test_free_text_needs_the_narrator_mode():
    console = Console(make_game(), "hero", io.StringIO(), io.StringIO())

    console.handle("ataco al goblin con todas mis fuerzas")
    assert "narrador" in console.stream_out.getvalue()

    console.handle("narrador")
    console._dungeon_master = _BrokenDungeonMaster()
    console.handle("ataco al goblin con todas mis fuerzas")
    assert "DM no disponible" in console.stream_out.getvalue()


class _BrokenDungeonMaster:
    def play(self, *_args, **_kwargs):
        raise DungeonMasterError("sin credencial")


def test_a_missing_credential_becomes_a_readable_error():
    # El SDK falla con TypeError, no con AuthenticationError, cuando no hay clave.
    client = fake_client(TypeError(
        '"Could not resolve authentication method. Expected one of api_key, '
        'auth_token, or credentials to be set."'
    ))

    with pytest.raises(DungeonMasterError, match="ANTHROPIC_API_KEY"):
        DungeonMaster(client).interpret(make_game(), "hero", "hola")


def test_an_unrelated_error_is_not_swallowed():
    client = fake_client(TypeError("argumento invalido en mi codigo"))

    with pytest.raises(TypeError, match="argumento invalido"):
        DungeonMaster(client).interpret(make_game(), "hero", "hola")


# -- memoria de campana -------------------------------------------------------


def test_both_prompts_carry_the_campaign_memory():
    engine = make_game()
    engine.memory.facts["muerte:rata"] = "La rata gigante murio."
    client = fake_client(tool_call(NO_ACTION, reason="x"), narration("..."))

    DungeonMaster(client).play(engine, "hero", "que fue de la rata?")

    for call in client.messages.calls:
        prompt = call["messages"][0]["content"]
        assert "MEMORIA DE CAMPANA" in prompt
        assert "La rata gigante murio." in prompt


def test_the_turn_is_written_into_memory_after_the_action():
    engine = make_game()
    engine.world.get_character("hero").position = (4, 3)
    client = fake_client(
        tool_call("attack", target="goblin-1", weapon=None),
        narration("Tu espada abre al goblin de hombro a cadera."),
    )

    DungeonMaster(client).play(engine, "hero", "ataco al goblin")

    entries = [(entry.kind, entry.text) for entry in engine.memory.entries]
    # La cronica del evento va primero; luego el turno del jugador y la narracion.
    assert entries[0] == ("cronica", "Goblin murio.")
    assert entries[-2] == ("jugador", "ataco al goblin")
    assert entries[-1] == ("dm", "Tu espada abre al goblin de hombro a cadera.")


def test_remembering_can_be_switched_off():
    engine = make_game()
    client = fake_client(tool_call(NO_ACTION, reason="x"), narration("Nada."))

    DungeonMaster(client).play(engine, "hero", "hola", remember=False)

    assert engine.memory.entries == []


# -- secuencias de acciones ---------------------------------------------------


def sequence(*calls):
    """Una respuesta con varios tool_use, como cuando el jugador pide una secuencia."""
    return FakeResponse([ToolUseBlock(name, parameters) for name, parameters in calls])


def test_a_compound_sentence_becomes_a_sequence_of_actions():
    engine = make_game()
    client = fake_client(
        sequence(("move", {"x": 4, "y": 3}),
                 ("attack", {"target": "goblin-1", "weapon": None})),
        narration("Cierras la distancia y hundes el acero."),
    )

    turn = DungeonMaster(client).play(engine, "hero", "me acerco al goblin y le clavo la espada")

    assert [one.action for one in turn.intents] == ["move", "attack"]
    assert len(turn.results) == 2
    assert engine.world.get_character("hero").position == (4, 3)
    assert engine.world.get_character("goblin-1").hp < 9
    assert turn.error is None


def test_a_rejection_stops_the_sequence_but_keeps_what_already_happened():
    engine = make_game()
    client = fake_client(
        # Se mueve, pero no lo bastante cerca para que la espada alcance.
        sequence(("move", {"x": 2, "y": 2}),
                 ("attack", {"target": "goblin-1", "weapon": None})),
        narration("Avanzas, pero el bicho sigue lejos."),
    )

    turn = DungeonMaster(client).play(engine, "hero", "me acerco y le pego")

    assert engine.world.get_character("hero").position == (2, 2)  # el paso ocurrio
    assert len(turn.results) == 1
    assert "alcance" in turn.error
    assert engine.world.get_character("goblin-1").hp == 9


def test_the_narrator_receives_the_whole_sequence():
    engine = make_game()
    client = fake_client(
        sequence(("move", {"x": 4, "y": 3}),
                 ("attack", {"target": "goblin-1", "weapon": None})),
        narration("..."),
    )
    DungeonMaster(client).play(engine, "hero", "me acerco y ataco")

    prompt = client.messages.calls[1]["messages"][0]["content"]
    assert prompt.count("RESULTADO REAL:") == 2
    assert "('move', {'x': 4, 'y': 3})" in prompt


def test_a_runaway_sequence_is_capped():
    engine = make_game()
    client = fake_client(sequence(*[(NO_ACTION, {"reason": f"n{n}"}) for n in range(9)]),
                         narration("..."))

    turn = DungeonMaster(client).play(engine, "hero", "hago mil cosas")

    assert len(turn.intents) == MAX_INTENTS


# -- el turno no se pierde ----------------------------------------------------


def test_a_failed_narration_falls_back_to_the_mechanical_summary():
    engine = make_game()
    engine.world.get_character("hero").position = (4, 3)
    client = fake_client(
        tool_call("attack", target="goblin-1", weapon=None),
        DungeonMasterError("sobrecargada", retryable=True),
    )

    turn = DungeonMaster(client).play(engine, "hero", "ataco")

    # El ataque ocurrio de verdad y se cuenta, aunque el narrador no respondiera.
    assert turn.acted is True
    assert "Aldric acierta a Goblin" in turn.narration
    assert engine.memory.entries[-1].text == turn.narration


def test_a_failed_narration_still_reports_a_rule_rejection():
    engine = make_game()
    client = fake_client(
        tool_call("attack", target="goblin-1", weapon=None),
        DungeonMasterError("sobrecargada", retryable=True),
    )

    turn = DungeonMaster(client).play(engine, "hero", "ataco de lejos")

    assert turn.acted is False
    assert "No puede ser:" in turn.narration
    assert "alcance" in turn.narration


def test_overloaded_and_connection_errors_are_marked_retryable():
    import anthropic

    dungeon_master = DungeonMaster(fake_client())
    overloaded = anthropic.APIStatusError(
        "Overloaded", response=_FakeHttpResponse(529), body=None)
    assert dungeon_master._translate(overloaded).retryable is True
    assert dungeon_master._translate(
        anthropic.APIConnectionError(request=None)).retryable is True

    not_found = anthropic.NotFoundError(
        "nope", response=_FakeHttpResponse(404), body=None)
    assert dungeon_master._translate(not_found).retryable is False


class _FakeHttpResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.headers = {}
        self.request = None


def test_the_console_says_the_turn_is_intact_after_a_transient_failure():
    console = Console(make_game(), "hero", io.StringIO(), io.StringIO())
    console._dungeon_master = _OverloadedDungeonMaster()

    console.handle("dm ataco al goblin")

    text = console.stream_out.getvalue()
    assert "sobrecargada" in text
    assert "Tu turno sigue intacto" in text


class _OverloadedDungeonMaster:
    def play(self, *_args, **_kwargs):
        raise DungeonMasterError("La API esta sobrecargada (529).", retryable=True)


def test_the_console_prints_the_whole_sequence():
    engine = make_game()
    console = Console(engine, "hero", io.StringIO(), io.StringIO())
    console._dungeon_master = DungeonMaster(fake_client(
        sequence(("move", {"x": 4, "y": 3}),
                 ("attack", {"target": "goblin-1", "weapon": None})),
        narration("Cierras y golpeas."),
    ))

    console.handle("dm me acerco y le pego")

    text = console.stream_out.getvalue()
    assert "Cierras y golpeas." in text
    assert "move {'x': 4, 'y': 3} + attack {'target': 'goblin-1'}" in text


# -- apertura narrada ---------------------------------------------------------


def test_the_dm_opens_the_scene_from_the_briefing():
    engine = make_game()
    client = fake_client(narration("El aire de la bodega huele a moho y a algo peor."))

    text = DungeonMaster(client).open_scene(engine, "hero")

    assert text == "El aire de la bodega huele a moho y a algo peor."
    request = client.messages.calls[0]
    assert "tools" not in request  # abrir escena no elige acciones
    assert "Datos de la apertura:" in request["messages"][0]["content"]
    assert "no inventes" in request["system"][0]["text"].lower()


def test_the_console_opening_uses_the_written_hook_without_the_dm():
    engine = build_campaign(CampaignSetup(scenario="cripta"))
    console = Console(engine, "hero-aldric", io.StringIO(), io.StringIO())

    text = console.opening()

    assert "La aldea enterro a su ultimo rey" in text
    assert "Callar al Rey:" in text
    assert "'intro' para releer esto" in text


def test_the_console_opening_is_narrated_when_the_dm_is_on():
    engine = build_campaign(CampaignSetup(scenario="cripta"))
    console = Console(engine, "hero-aldric", io.StringIO(), io.StringIO())
    console.narrator = True
    console._dungeon_master = DungeonMaster(fake_client(
        narration("La piedra del sello aun esta tibia.")))

    text = console.opening()

    assert "La piedra del sello aun esta tibia." in text
    assert "La aldea enterro a su ultimo rey" not in text
    assert "Callar al Rey:" in text
    # La apertura queda en la memoria como primera narracion del DM.
    assert engine.memory.entries[-1].text == "La piedra del sello aun esta tibia."


def test_a_failed_opening_falls_back_to_the_written_hook():
    engine = build_campaign(CampaignSetup(scenario="cripta"))
    console = Console(engine, "hero-aldric", io.StringIO(), io.StringIO())
    console.narrator = True
    console._dungeon_master = _OverloadedDungeonMaster()

    text = console.opening()

    assert "La aldea enterro a su ultimo rey" in text
    assert "no ha podido abrir la escena" in console.stream_out.getvalue()


def test_the_intro_command_reshows_the_briefing_without_calling_the_model():
    engine = build_campaign(CampaignSetup(scenario="torre"))
    console = Console(engine, "hero-aldric", io.StringIO(), io.StringIO())
    console.narrator = True
    console._dungeon_master = _OverloadedDungeonMaster()  # si lo llamara, fallaria

    console.handle("intro")

    text = console.stream_out.getvalue()
    assert "El alquimista subio a su laboratorio" in text
    assert "no ha podido abrir la escena" not in text
