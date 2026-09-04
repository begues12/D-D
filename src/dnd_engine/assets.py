"""Fuentes y texturas, sin dependencias ni instalaciones.

Dos cosas que hacen que la ventana parezca un juego y no un formulario:

- **Las tipografias** viajan con el repositorio (`assets/fonts`, licencia OFL) y
  se cargan *solo para este proceso* con `AddFontResourceEx`. No se instalan en
  el sistema, no piden permisos de administrador y desaparecen al cerrar. Si
  algo falla -otro sistema operativo, un fichero que no esta-, se usa la fuente
  de reserva y la aplicacion sigue.

- **Las texturas** -pergamino y cuero- se dibujan aqui, pixel a pixel, y se
  codifican como PNG con `zlib` de la libreria estandar. Ni Pillow, ni imagenes
  descargadas, ni licencias que revisar: son ruido de valor con dos octavas y un
  vinateado, siempre iguales porque la semilla es fija.
"""

from __future__ import annotations

import base64
import ctypes
import math
import struct
import sys
import zlib
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "assets"
FONT_DIR = ASSETS / "fonts"

# Nombre de familia de cada fichero, que es como lo vera Tk una vez cargado.
FONT_FILES = {
    "Cinzel-Variable.ttf": "Cinzel",
    "IMFellEnglish-Regular.ttf": "IM FELL English",
    "MedievalSharp-Regular.ttf": "MedievalSharp",
}

FR_PRIVATE = 0x10


@lru_cache(maxsize=1)
def install_fonts() -> set[str]:
    """Carga las fuentes del repositorio para este proceso. Devuelve las que valen."""
    if sys.platform != "win32":
        return set()
    loaded: set[str] = set()
    for filename, family in FONT_FILES.items():
        path = FONT_DIR / filename
        if not path.exists():
            continue
        try:
            added = ctypes.windll.gdi32.AddFontResourceExW(str(path), FR_PRIVATE, 0)
        except OSError:
            continue
        if added:
            loaded.add(family)
    return loaded


def font_family(preferred: str, fallback: str) -> str:
    """La fuente bonita si se ha podido cargar; si no, una que hay en todas partes."""
    return preferred if preferred in install_fonts() else fallback


# -- texturas ------------------------------------------------------------------


def _noise(x: int, y: int, seed: int) -> float:
    """Ruido de valor: siempre el mismo para las mismas coordenadas."""
    value = (x * 374761393 + y * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    value = (value ^ (value >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((value ^ (value >> 16)) & 0xFFFF) / 65535.0


def _smooth(x: float, y: float, cell: int, seed: int) -> float:
    """Interpola el ruido de la rejilla para que no se vean los cuadros."""
    grid_x, grid_y = int(x // cell), int(y // cell)
    fraction_x, fraction_y = (x % cell) / cell, (y % cell) / cell
    # Suavizado en S: mata la sensacion de malla.
    fraction_x = fraction_x * fraction_x * (3 - 2 * fraction_x)
    fraction_y = fraction_y * fraction_y * (3 - 2 * fraction_y)
    top = (_noise(grid_x, grid_y, seed) * (1 - fraction_x)
           + _noise(grid_x + 1, grid_y, seed) * fraction_x)
    bottom = (_noise(grid_x, grid_y + 1, seed) * (1 - fraction_x)
              + _noise(grid_x + 1, grid_y + 1, seed) * fraction_x)
    return top * (1 - fraction_y) + bottom * fraction_y


def _texture_rows(width: int, height: int, base: tuple[int, int, int],
                  grain: int, seed: int, vignette: float) -> bytes:
    """Filas PNG en crudo: el color base, mas grano, mas sombra en los bordes."""
    rows = bytearray()
    half_x, half_y = width / 2, height / 2
    for y in range(height):
        rows.append(0)                      # filtro 'none' de PNG
        for x in range(width):
            shade = (_smooth(x, y, 24, seed) - 0.5) * 2 + (_smooth(x, y, 5, seed + 7) - 0.5)
            edge = 1.0 - vignette * max(abs(x - half_x) / half_x,
                                        abs(y - half_y) / half_y) ** 3
            for channel in base:
                value = (channel + shade * grain) * edge
                rows.append(max(0, min(255, int(value))))
    return bytes(rows)


def _png(width: int, height: int, rows: bytes) -> bytes:
    """Un PNG RGB minimo, escrito a mano para no depender de nadie."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


# Cada textura: color base, cuanto grano y cuanta sombra al borde.
TEXTURES = {
    "parchment": ((228, 214, 180), 26, 3, 0.22),
    "leather": ((32, 35, 44), 14, 11, 0.35),
    "wood": ((58, 42, 30), 22, 19, 0.30),
}


@lru_cache(maxsize=8)
def texture(name: str, size: int = 128) -> str:
    """La textura como PNG en base64, lista para `tk.PhotoImage(data=...)`."""
    base, grain, seed, vignette = TEXTURES[name]
    rows = _texture_rows(size, size, base, grain, seed, vignette)
    return base64.b64encode(_png(size, size, rows)).decode("ascii")
