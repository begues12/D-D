"""Tests de la capa de proveedores: la casa de IA se puede cambiar.

El ultimo bloque monta un proveedor de mentira, sin nada de Anthropic, y juega
un turno completo con el. Es la prueba de que el motor no depende de un SDK.
"""

import os

import pytest

from dnd_engine.ai_dm import DungeonMaster, DungeonMasterError
from dnd_engine.credentials import _storage_path
from dnd_engine.providers import (
    DEFAULT_PROVIDER,
    PROVIDER_ENV,
    PROVIDERS,
    AnthropicProvider,
    Provider,
    ProviderError,
    Reply,
    TextBlock,
    ToolUseBlock,
    get_provider,
)

from test_ai_dm import make_game


# -- el registro ---------------------------------------------------------------


def test_the_default_provider_is_anthropic_for_now():
    assert get_provider().id == DEFAULT_PROVIDER
    assert get_provider("anthropic").name == "Anthropic"
    assert get_provider(PROVIDERS["anthropic"]) is PROVIDERS["anthropic"]


def test_the_provider_can_be_chosen_with_an_environment_variable(monkeypatch):
    monkeypatch.setenv(PROVIDER_ENV, "ANTHROPIC")

    assert get_provider().id == "anthropic"


def test_an_unknown_provider_says_which_ones_there_are():
    with pytest.raises(ValueError, match="No conozco la IA 'skynet'"):
        get_provider("skynet")


def test_each_provider_keeps_its_own_key_file():
    assert _storage_path("anthropic").name == "anthropic.key"
    assert _storage_path("otra").name == "otra.key"


def test_a_provider_reads_and_forgets_its_key(monkeypatch):
    provider = AnthropicProvider()
    monkeypatch.delenv(provider.env_var, raising=False)
    assert provider.is_configured() is False

    provider.use_key("  sk-test  ")
    assert os.environ[provider.env_var] == "sk-test"
    assert provider.is_configured() is True

    provider.forget_key()
    assert provider.is_configured() is False


# -- la respuesta neutra -------------------------------------------------------


def test_a_reply_reads_its_text_and_its_tools():
    reply = Reply((TextBlock("Bajas al "), ToolUseBlock("t1", "move", {"x": 1}),
                   TextBlock("sotano.")))

    assert reply.text == "Bajas al sotano."
    assert [one.name for one in reply.tool_uses()] == ["move"]
    assert reply.tool_uses("attack") == []


def test_the_anthropic_answer_becomes_a_neutral_reply():
    class Block:
        def __init__(self, **values):
            self.__dict__.update(values)

    class Response:
        content = [Block(type="text", text="hola"),
                   Block(type="tool_use", id="t1", name="attack", input={"target": "x"}),
                   Block(type="thinking")]        # lo que no se entiende, se cae
        stop_reason = "tool_use"

    reply = AnthropicProvider().normalize(Response())

    assert reply.text == "hola"
    assert reply.tool_uses()[0].input == {"target": "x"}
    assert reply.stop_reason == "tool_use"
    assert len(reply.content) == 2


# -- errores traducidos --------------------------------------------------------


class FakeHttpResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.headers = {}
        self.request = None


def test_overloaded_and_connection_errors_are_retryable():
    import anthropic

    provider = AnthropicProvider()
    overloaded = anthropic.APIStatusError(
        "Overloaded", response=FakeHttpResponse(529), body=None)

    assert provider.translate(overloaded)[1] is True
    assert provider.translate(anthropic.APIConnectionError(request=None))[1] is True
    assert provider.translate(anthropic.NotFoundError(
        "nope", response=FakeHttpResponse(404), body=None))[1] is False


def test_a_missing_credential_is_explained_not_dumped():
    message, retryable = AnthropicProvider().translate(
        TypeError("Could not resolve authentication method"))

    assert "ANTHROPIC_API_KEY" in message
    assert retryable is False


def test_an_error_from_somewhere_else_is_not_translated():
    assert AnthropicProvider().translate(ZeroDivisionError()) is None


def test_without_the_sdk_the_client_says_what_to_install(monkeypatch):
    provider = AnthropicProvider()
    monkeypatch.setattr(provider, "module", lambda: None)

    with pytest.raises(ProviderError, match="pip install"):
        provider.create_client()


def test_the_dungeon_master_turns_that_into_its_own_error(monkeypatch):
    provider = AnthropicProvider()
    monkeypatch.setattr(provider, "module", lambda: None)

    with pytest.raises(DungeonMasterError, match="pip install"):
        DungeonMaster(provider=provider)


# -- otra IA cualquiera --------------------------------------------------------


class FakeProvider(Provider):
    """Una casa inventada: ni SDK de Anthropic ni nada que se le parezca."""

    id = "fake"
    name = "Fake AI"
    env_var = "FAKE_AI_KEY"
    default_model = "fake-1"
    package = "no_existe"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def create_client(self, retries=5):
        return object()

    def create_message(self, client, **request):
        self.requests.append(request)
        answer = self.replies.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def assistant_echo(self, reply):
        return reply.raw

    def translate(self, error):
        return ("la IA de mentira se ha caido", False) if isinstance(error, KeyError) else None


def test_a_new_provider_plays_a_whole_turn_without_anthropic():
    engine = make_game()
    provider = FakeProvider(
        Reply((ToolUseBlock("t1", "approach", {"target": "goblin-1"}),), "tool_use"),
        Reply((TextBlock("Cruzas la bodega hasta tenerlo al alcance."),)),
    )

    turn = DungeonMaster(provider=provider).play(engine, "hero", "le pego")

    assert turn.intent.action == "approach"
    assert turn.acted is True
    assert turn.narration == "Cruzas la bodega hasta tenerlo al alcance."
    assert engine.world.get_character("hero").position != (0, 0)


def test_the_model_and_the_request_come_from_the_provider():
    provider = FakeProvider(Reply((TextBlock("bien"),)))

    session = DungeonMaster(provider=provider)
    session.open_scene(make_game(), "hero")

    assert session.model == "fake-1"
    request = provider.requests[0]
    assert request["max_tokens"] == session.max_tokens
    assert request["effort"] == "low"
    assert "tools" not in request          # narrar no lleva herramientas


def test_a_provider_error_reaches_the_player_translated():
    provider = FakeProvider(KeyError("boom"))

    with pytest.raises(DungeonMasterError, match="la IA de mentira se ha caido"):
        DungeonMaster(provider=provider).interpret(make_game(), "hero", "ataco")


def test_an_untranslated_error_is_not_swallowed():
    provider = FakeProvider(RuntimeError("algo raro"))

    with pytest.raises(RuntimeError, match="algo raro"):
        DungeonMaster(provider=provider).interpret(make_game(), "hero", "ataco")


def test_a_refusal_is_reported_as_such():
    provider = FakeProvider(Reply((), "refusal"))

    with pytest.raises(DungeonMasterError, match="declino responder"):
        DungeonMaster(provider=provider).interpret(make_game(), "hero", "ataco")
