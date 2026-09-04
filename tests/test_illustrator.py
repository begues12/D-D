"""Tests de la cronica ilustrada. Ninguno llama a la API."""

import base64

import pytest

from dnd_engine import assets
from dnd_engine.campaign import CampaignSetup, PlayerSetup, build_campaign
from dnd_engine.events import Event
from dnd_engine.illustrator import (
    EMBLEMS,
    Illustration,
    Illustrator,
    scene_of,
    should_illustrate,
)
from dnd_engine.providers import Reply, TextBlock, ToolUseBlock

from test_providers import FakeProvider


def game(scenario="cripta"):
    return build_campaign(CampaignSetup(
        players=[PlayerSetup("Nel", "mago")], scenario=scenario))


def lamina(title="El pozo", caption="Piedra y musgo.", emblem="agua"):
    return Reply((ToolUseBlock("t1", "illustrate", {
        "title": title, "caption": caption, "emblem": emblem}),), "tool_use")


# -- sin IA --------------------------------------------------------------------


def test_the_engine_alone_can_draw_the_scene():
    scene = scene_of(game(), "hero-nel")

    assert scene.title == "Vestibulo de la cripta"
    assert "Columnas rotas" in scene.caption
    assert scene.emblem in EMBLEMS
    assert scene.drawn is False


def test_the_scene_says_who_and_what_is_there():
    engine = game("taberna")

    scene = scene_of(engine, "hero-nel")

    assert "Marta la tabernera" in scene.caption          # quien
    assert "Llave de la bodega" in scene.caption          # y que hay


@pytest.mark.parametrize("scenario, emblem", [
    ("cripta", "hueso"), ("pantano", "agua"), ("taberna", "moneda"),
    # La torre empieza en una escalera: no hay nada que reconocer y sale la luna.
    ("torre", "luna"),
])
def test_the_emblem_is_guessed_from_the_room_not_the_campaign(scenario, emblem):
    assert scene_of(game(scenario), "hero-nel").emblem == emblem


def test_only_the_events_worth_a_plate_trigger_one():
    assert should_illustrate([Event("PLAYER_ENTERED_LOCATION", "hero")]) is True
    assert should_illustrate([Event("QUEST_COMPLETED")]) is True
    assert should_illustrate([Event("PLAYER_ATTACK", "hero"),
                              Event("CHARACTER_MOVED", "hero")]) is False
    assert should_illustrate([]) is False


# -- con una IA de texto -------------------------------------------------------


def test_the_model_writes_the_plate():
    engine = game()
    illustrator = Illustrator(provider=FakeProvider(lamina()))

    scene = illustrator.illustrate(engine, "hero-nel", "Bajas los peldanos.")

    assert (scene.title, scene.caption, scene.emblem) == (
        "El pozo", "Piedra y musgo.", "agua")
    assert scene.drawn is False


def test_the_prompt_carries_the_place_and_the_narration():
    provider = FakeProvider(lamina())

    Illustrator(provider=provider).illustrate(game(), "hero-nel", "Bajas los peldanos.")

    sent = provider.requests[0]["messages"][0]["content"]
    assert "Vestibulo de la cripta" in sent
    assert "Bajas los peldanos." in sent


def test_an_invented_emblem_falls_back_to_one_that_can_be_drawn():
    illustrator = Illustrator(provider=FakeProvider(lamina(emblem="dragon")))

    scene = illustrator.illustrate(game(), "hero-nel")

    assert scene.emblem in EMBLEMS


def test_if_the_model_does_not_use_the_tool_the_engine_answers():
    illustrator = Illustrator(provider=FakeProvider(Reply((TextBlock("bonito sitio"),))))

    scene = illustrator.illustrate(game(), "hero-nel")

    assert scene.title == "Vestibulo de la cripta"


# -- con una IA que dibuja -----------------------------------------------------


class DrawingProvider(FakeProvider):
    """El dia que una casa sepa dibujar, esto es todo lo que hara falta."""

    supports_images = True

    def __init__(self, image, *replies):
        super().__init__(*replies)
        self.image = image
        self.prompts: list[str] = []

    def generate_image(self, client, prompt):
        self.prompts.append(prompt)
        return self.image


def test_a_provider_that_draws_puts_its_image_in_the_plate():
    png = base64.b64decode(assets.texture("parchment", 32))
    provider = DrawingProvider(png)

    scene = Illustrator(provider=provider).illustrate(game(), "hero-nel")

    assert scene.drawn is True
    assert scene.image == png
    assert "Vestibulo de la cripta" in provider.prompts[0]
    assert provider.requests == []            # no hace falta la llamada de texto


def test_if_the_drawing_fails_the_text_plate_still_arrives():
    provider = DrawingProvider(None, lamina(title="Sin dibujo"))

    scene = Illustrator(provider=provider).illustrate(game(), "hero-nel")

    assert scene.drawn is False
    assert scene.title == "Sin dibujo"


def test_an_illustration_knows_whether_it_is_drawn():
    assert Illustration("t", "c").drawn is False
    assert Illustration("t", "c", image=b"\x89PNG").drawn is True
