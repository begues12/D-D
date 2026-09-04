"""Tests de las fuentes y las texturas: sin dependencias y siempre iguales."""

import base64
import struct

import pytest

from dnd_engine import assets


# -- fuentes -------------------------------------------------------------------


def test_the_fonts_travel_with_the_repository():
    for filename in assets.FONT_FILES:
        assert (assets.FONT_DIR / filename).exists(), filename
    # Cada familia con su licencia al lado.
    assert list(assets.FONT_DIR.glob("OFL-*.txt"))


def test_a_font_that_is_not_there_falls_back():
    assert assets.font_family("Fuente Que No Existe", "Georgia") == "Georgia"


def test_the_downloaded_font_is_used_when_it_loads():
    loaded = assets.install_fonts()
    if not loaded:
        pytest.skip("las fuentes solo se cargan en Windows")
    family = next(iter(loaded))
    assert assets.font_family(family, "Georgia") == family


# -- texturas ------------------------------------------------------------------


def png_size(data: str) -> tuple[int, int]:
    raw = base64.b64decode(data)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">2I", raw[16:24])


@pytest.mark.parametrize("name", sorted(assets.TEXTURES))
def test_every_texture_is_a_readable_png(name):
    assert png_size(assets.texture(name, 32)) == (32, 32)


def test_a_texture_is_always_the_same():
    """La semilla es fija: dos ejecuciones dan el mismo fondo."""
    assets.texture.cache_clear()
    first = assets.texture("parchment", 24)
    assets.texture.cache_clear()
    assert assets.texture("parchment", 24) == first


def test_textures_are_cached_because_they_cost_lo_suyo():
    assets.texture.cache_clear()
    assets.texture("leather", 16)
    hits_before = assets.texture.cache_info().hits
    assets.texture("leather", 16)
    assert assets.texture.cache_info().hits == hits_before + 1


def test_two_skins_do_not_look_alike():
    assert assets.texture("parchment", 16) != assets.texture("leather", 16)


def test_an_unknown_skin_is_a_mistake_not_a_grey_square():
    with pytest.raises(KeyError):
        assets.texture("terciopelo", 16)
