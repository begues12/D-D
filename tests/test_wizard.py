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
    yield game
    game._executor.shutdown(wait=False)
    for child in root.winfo_children():
        child.destroy()
    # Las texturas son PhotoImage: hay que soltarlas con la raiz todavia viva.
    game.console = None
    del game
    gc.collect()


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


def test_six_adventures_are_offered_written_and_to_invent(window):
    adventures = window.wizard.adventures

    assert len(adventures) == 6
    assert [one.kicker for one in adventures] == ["ESCRITA"] * 4 + ["IA"] * 2
    assert all(one.empty for one in adventures if one.kicker == "IA")


def test_each_step_refuses_to_advance_empty(window):
    wizard = window.wizard

    wizard.next_step()
    assert wizard.step == 0 and "aventura" in wizard.status_var.get()

    wizard.choose_adventure(wizard.adventures[0])
    wizard.next_step()
    wizard.next_step()
    assert wizard.step == 1 and "arquetipo" in wizard.status_var.get()

    wizard.choose_archetype("mago")
    wizard.next_step()
    wizard.name_var.set("   ")
    wizard.next_step()
    assert wizard.step == 2 and "nombre" in wizard.status_var.get()
    assert window.console is None


def test_choosing_a_card_lights_only_that_one(window):
    wizard = window.wizard

    wizard.choose_adventure(wizard.adventures[2])

    lit = [one for one, card in wizard.cards.items() if card.selected]
    assert lit == [wizard.adventures[2].id]


def test_going_back_keeps_what_was_chosen(window):
    wizard = window.wizard
    wizard.choose_adventure(wizard.adventures[1])
    wizard.next_step()
    wizard.choose_archetype("picaro")

    wizard.previous_step()

    assert wizard.step == 0
    assert wizard.cards[wizard.adventures[1].id].selected
    wizard.next_step()
    assert wizard.cards["picaro"].selected


# -- las aventuras inventadas -------------------------------------------------


def test_the_ai_fills_the_empty_slots(window):
    wizard = window.wizard
    wizard.hint_var.set("algo con agua")

    wizard.invent()
    pump(window)

    assert [one.kicker for one in wizard.adventures] == ["ESCRITA"] * 4 + ["INVENTADA"] * 2
    assert wizard._forge.hints == ["algo con agua"]
    assert wizard._forge.avoided == [()]
    assert wizard._forge.built == []          # proponer no monta nada


def test_inventing_again_replaces_only_the_invented_ones(window):
    wizard = window.wizard
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
    wizard.invent()
    pump(window)

    wizard.choose_adventure(wizard.adventures[4])
    wizard.next_step()
    pump(window)

    assert wizard._forge.built == ["idea-1-1"]
    assert wizard.adventures[4].blueprint is not None
    assert wizard.step == 1                    # avanza solo cuando esta montada


def test_an_invented_adventure_ends_up_in_the_game(window):
    wizard = window.wizard
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
    wizard.choose_adventure(wizard.adventures[0])
    wizard.next_step()

    finish(window, "Aldric", "guerrero")

    assert window.console is not None
    assert wizard._forge.proposals == 0
    assert window.console.engine.world.get_character("hero-aldric").hp == 22


def test_the_game_starts_with_the_dm_the_wizard_was_told(window):
    wizard = window.wizard
    wizard.ai_enabled_var.set(False)
    wizard.choose_adventure(wizard.adventures[0])
    wizard.next_step()

    finish(window)

    assert window.console.narrator is False
