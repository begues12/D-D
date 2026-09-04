"""Tests de la columna ilustrada dentro de una ventana de verdad.

Como los del asistente: si no hay escritorio, se saltan solos.
"""

import gc
import time

import pytest

from dnd_engine.illustrator import Illustration

from test_campaign import FakeForge

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def root():
    try:
        interpreter = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"sin entorno grafico: {error}")
    interpreter.withdraw()
    yield interpreter
    interpreter.destroy()


@pytest.fixture
def window(root):
    """Una partida ya empezada, sin IA: la cronica la llena el motor."""
    from dnd_engine.gui import GameWindow

    game = GameWindow(root)
    wizard = game.wizard
    wizard._forge = FakeForge()
    wizard.ai_enabled_var.set(False)
    wizard.choose_adventure(wizard.adventures[0])      # el sotano del Dragon Rojo
    wizard.next_step()
    wizard.choose_archetype("guerrero")
    wizard.next_step()
    wizard.name_var.set("Aldric")
    wizard.next_step()
    root.update()
    yield game
    game._executor.shutdown(wait=False)
    for child in root.winfo_children():
        child.destroy()
    game.console = None
    del game
    gc.collect()


def settle(window, seconds: float = 0.4) -> None:
    end = time.time() + seconds
    while time.time() < end:
        window.root.update()
        time.sleep(0.01)


def test_a_fresh_column_says_what_it_is_for(window):
    from dnd_engine.chronicle import ChronicleColumn

    column = ChronicleColumn(window.root)
    try:
        assert column.plates == []
        assert column._placeholder is not None
    finally:
        column.destroy()


def test_the_opening_scene_is_already_a_plate(window):
    """Nada mas entrar, la cronica tiene la escena con la que empieza todo."""
    assert len(window.chronicle.plates) == 1
    assert window.chronicle._placeholder is None


def test_plates_pile_up(window):
    before = len(window.chronicle.plates)

    for number in range(3):
        window.chronicle.add(Illustration(f"Escena {number}", "Un sitio.", "luna"))

    assert len(window.chronicle.plates) == before + 3


def test_without_ai_the_engine_fills_the_plate(window):
    before = len(window.chronicle.plates)

    window.illustrate()
    settle(window)

    assert len(window.chronicle.plates) == before + 1
    assert window._illustrator is None          # no se ha creado ningun cliente


def test_moving_to_a_new_room_adds_a_plate(window):
    before = len(window.chronicle.plates)

    window.submit("coger cellar-key")
    settle(window)
    window.submit("abrir trapdoor")
    settle(window)
    window.submit("ir cellar")
    settle(window)

    assert len(window.chronicle.plates) == before + 1


def test_looking_around_does_not_add_a_plate(window):
    window.illustrate()
    settle(window)
    before = len(window.chronicle.plates)

    window.submit("mirar")
    settle(window)

    assert len(window.chronicle.plates) == before


def test_every_emblem_can_be_drawn(window):
    """Ninguno de los simbolos revienta al pintarse."""
    from dnd_engine.illustrator import EMBLEMS

    before = len(window.chronicle.plates)
    for emblem in EMBLEMS:
        window.chronicle.add(Illustration("Prueba", "Un sitio cualquiera.", emblem))
    settle(window, 0.3)

    assert len(window.chronicle.plates) == before + len(EMBLEMS)


def test_a_drawn_plate_shows_the_image(window):
    from dnd_engine import assets
    import base64

    png = base64.b64decode(assets.texture("parchment", 32))
    window.chronicle.add(Illustration("Lamina", "Con dibujo.", "luna", image=png))

    plate = window.chronicle.plates[-1]
    assert plate.image is not None
    assert plate.image.width() == 32
