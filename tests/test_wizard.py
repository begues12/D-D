"""Tests del asistente grafico. No hay red: la fragua se inyecta.

Tkinter necesita un escritorio; donde no lo haya, estos tests se saltan solos.
"""

import gc
import time

import pytest

from test_campaign import FORGED, FakeForge

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def root():
    """Una sola raiz para todo el modulo: crear y destruir Tk en bucle lo rompe."""
    try:
        interpreter = tk.Tk()
    except tk.TclError as error:                       # sin escritorio
        pytest.skip(f"sin entorno grafico: {error}")
    interpreter.withdraw()
    yield interpreter
    interpreter.destroy()


@pytest.fixture
def window(root):
    from dnd_engine.gui import GameWindow

    game = GameWindow(root)
    game.wizard._forge = FakeForge()
    game.wizard.ai_enabled_var.set(False)     # ninguna llamada de verdad
    yield game
    game._executor.shutdown(wait=False)
    for child in root.winfo_children():
        child.destroy()
    # Las texturas son PhotoImage: hay que soltarlas con la raiz todavia viva.
    game.console = None
    del game
    gc.collect()


def to_adventures(window) -> None:
    """Pasa el primer paso -la IA- y deja el asistente en las aventuras."""
    window.wizard.next_step()


def pump(window, timeout: float = 5.0) -> None:
    """Corre el bucle de eventos hasta que la fragua deja de trabajar."""
    end = time.time() + timeout
    while window.wizard._busy and time.time() < end:
        window.root.update()
        time.sleep(0.01)
    window.root.update()


def finish(window, name: str = "Nel", archetype: str = "mago") -> None:
    window.wizard.choose_archetype(archetype)
    window.wizard.next_step()
    window.wizard.name_var.set(name)
    window.wizard.next_step()
    pump(window)


# -- el primer paso -----------------------------------------------------------


def test_the_first_step_is_choosing_the_ai(window):
    from dnd_engine.wizard import STEPS

    assert STEPS[0] == "LA IA"
    assert window.wizard.step == 0
    assert window.wizard.provider.id == "anthropic"
    assert window.wizard.model == window.wizard.provider.default_model


def test_every_model_of_the_provider_has_its_own_card(window):
    wizard = window.wizard

    lit = [one for one in wizard.provider.models if wizard.cards[one.id].selected]

    assert len(wizard.provider.models) >= 2
    assert [one.id for one in lit] == [wizard.model]


def test_choosing_a_model_lights_only_that_one(window):
    window.wizard.choose_model("claude-haiku-4-5")

    assert window.wizard.model == "claude-haiku-4-5"
    assert window.wizard.cards["claude-haiku-4-5"].selected
    assert not window.wizard.cards["claude-opus-5"].selected


def test_the_ai_cannot_be_left_on_without_a_key(window):
    window.wizard.api_key_var.set("")
    window.wizard.ai_enabled_var.set(True)

    window.wizard.next_step()

    assert window.wizard.step == 0
    assert "clave" in window.wizard.status_var.get()


def test_without_the_dm_the_key_is_not_required(window):
    window.wizard.api_key_var.set("")
    window.wizard.ai_enabled_var.set(False)

    window.wizard.next_step()

    assert window.wizard.step == 1


def test_the_chosen_ai_travels_with_the_campaign(window):
    from dnd_engine.campaign import CampaignSetup

    wizard = window.wizard
    wizard.choose_model("claude-sonnet-5")
    to_adventures(window)
    wizard.choose_adventure(wizard.adventures[0])
    wizard.next_step()

    finish(window, "Aldric", "guerrero")

    setup = CampaignSetup.from_world(window.console.engine.world.world)
    assert (setup.ai_provider, setup.ai_model) == ("anthropic", "claude-sonnet-5")


def test_six_adventures_are_offered_written_and_to_invent(window):
    adventures = window.wizard.adventures

    assert len(adventures) == 6
    assert [one.kicker for one in adventures] == ["ESCRITA"] * 4 + ["IA"] * 2
    assert all(one.empty for one in adventures if one.kicker == "IA")


def test_each_step_refuses_to_advance_empty(window):
    wizard = window.wizard
    to_adventures(window)

    wizard.next_step()
    assert wizard.step == 1 and "aventura" in wizard.status_var.get()

    wizard.choose_adventure(wizard.adventures[0])
    wizard.next_step()
    wizard.next_step()
    assert wizard.step == 2 and "arquetipo" in wizard.status_var.get()

    wizard.choose_archetype("mago")
    wizard.next_step()
    wizard.name_var.set("   ")
    wizard.next_step()
    assert wizard.step == 3 and "nombre" in wizard.status_var.get()
    assert window.console is None


def test_choosing_an_adventure_lights_only_that_one(window):
    wizard = window.wizard
    to_adventures(window)

    wizard.choose_adventure(wizard.adventures[2])

    lit = [one for one, card in wizard.cards.items() if card.selected]
    assert lit == [wizard.adventures[2].id]


def test_going_back_keeps_what_was_chosen(window):
    wizard = window.wizard
    to_adventures(window)
    wizard.choose_adventure(wizard.adventures[1])
    wizard.next_step()
    wizard.choose_archetype("picaro")

    wizard.previous_step()

    assert wizard.step == 1
    assert wizard.cards[wizard.adventures[1].id].selected
    wizard.next_step()
    assert wizard.cards["picaro"].selected


# -- las aventuras inventadas -------------------------------------------------


def test_the_ai_fills_the_empty_slots(window):
    wizard = window.wizard
    to_adventures(window)
    wizard.hint_var.set("algo con agua")

    wizard.invent()
    pump(window)

    assert [one.kicker for one in wizard.adventures] == ["ESCRITA"] * 4 + ["INVENTADA"] * 2
    assert wizard._forge.hints == ["algo con agua"]
    assert wizard._forge.avoided == [()]
    assert wizard._forge.built == []          # proponer no monta nada


def test_inventing_again_replaces_only_the_invented_ones(window):
    wizard = window.wizard
    to_adventures(window)
    wizard.invent()
    pump(window)
    written = [one.name for one in wizard.adventures[:4]]

    wizard.invent()
    pump(window)

    assert [one.name for one in wizard.adventures[:4]] == written
    assert wizard._forge.avoided[1] == ("Aventura 1.1", "Aventura 1.2")
    assert [one.name for one in wizard.adventures[4:]] == ["Aventura 2.1", "Aventura 2.2"]


def test_the_world_is_built_only_when_the_invented_one_is_chosen(window):
    wizard = window.wizard
    to_adventures(window)
    wizard.invent()
    pump(window)

    wizard.choose_adventure(wizard.adventures[4])
    wizard.next_step()
    pump(window)

    assert wizard._forge.built == ["idea-1-1"]
    assert wizard.adventures[4].blueprint is not None
    assert wizard.step == 2                    # avanza solo cuando esta montada


def test_an_invented_adventure_ends_up_in_the_game(window):
    wizard = window.wizard
    to_adventures(window)
    wizard.invent()
    pump(window)
    wizard.choose_adventure(wizard.adventures[5])
    wizard.next_step()
    pump(window)

    finish(window, "Nel", "mago")

    assert window.console is not None
    world = window.console.engine.world
    assert world.location_of("hero-nel").id == FORGED["start"]
    assert world.get_character("cosa") is not None


def test_a_written_adventure_needs_no_ai_at_all(window):
    wizard = window.wizard
    to_adventures(window)
    wizard.choose_adventure(wizard.adventures[0])
    wizard.next_step()

    finish(window, "Aldric", "guerrero")

    assert window.console is not None
    assert wizard._forge.proposals == 0
    assert window.console.engine.world.get_character("hero-aldric").hp == 22


def test_the_game_starts_with_the_dm_the_wizard_was_told(window):
    wizard = window.wizard
    wizard.ai_enabled_var.set(False)
    to_adventures(window)
    wizard.choose_adventure(wizard.adventures[0])
    wizard.next_step()

    finish(window)

    assert window.console.narrator is False
