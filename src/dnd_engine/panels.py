"""Marcos con textura: el pergamino y la madera dorada de la interfaz.

`ttk` no sabe pintar fondos con textura ni esquinas labradas, asi que un panel
es un `Canvas` que pinta -textura embaldosada, filo dorado, florones en las
esquinas- y encima cuelga un marco normal donde el resto del codigo mete sus
widgets como siempre:

    panel = TexturedPanel(parent, "leather")
    ttk.Label(panel.body, text="...", style="Panel.TLabel").pack()

Todo se repinta al cambiar de tamano, asi que la ventana se puede maximizar sin
que el marco se descuadre. Los colores y las medidas salen de `theme.py`.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .assets import texture
from .theme import FONTS, PALETTE, SPACE

# Cuanto ocupan los florones de las esquinas.
CORNER = 18
BORDER = 3


class TexturedPanel(tk.Frame):
    """Un panel con fondo de textura, filo dorado y esquinas labradas."""

    def __init__(self, parent: tk.Misc, skin: str = "leather", padding: int | None = None,
                 corners: bool = True, accent: str | None = None) -> None:
        super().__init__(parent, bg=PALETTE["night"], highlightthickness=0, bd=0)
        self.skin = skin
        self.corners = corners
        self.accent = accent or PALETTE["gold_dark"]
        padding = SPACE["md"] if padding is None else padding

        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0,
                                bg=PALETTE["night"])
        self.canvas.pack(fill="both", expand=True)
        # La imagen se guarda en el objeto: Tk descarta las que no referencia nadie.
        self._tile = tk.PhotoImage(data=texture(skin))
        self._tiles: list[int] = []

        self.body = tk.Frame(self.canvas, bg=self._ground(), bd=0, highlightthickness=0)
        self._window = self.canvas.create_window(
            padding, padding, anchor="nw", window=self.body)
        self._padding = padding
        self.canvas.bind("<Configure>", self._repaint)

    def _ground(self) -> str:
        """El color liso que mejor casa con la textura, para los widgets de dentro."""
        return PALETTE["paper"] if self.skin == "parchment" else PALETTE["panel"]

    def _repaint(self, event) -> None:
        width, height = event.width, event.height
        self.canvas.delete("skin")
        step = self._tile.width()
        for y in range(0, height + step, step):
            for x in range(0, width + step, step):
                self.canvas.create_image(x, y, image=self._tile, anchor="nw", tags="skin")
        self.canvas.create_rectangle(
            1, 1, width - 1, height - 1, outline=self.accent, width=BORDER, tags="skin")
        self.canvas.create_rectangle(
            BORDER + 2, BORDER + 2, width - BORDER - 2, height - BORDER - 2,
            outline=PALETTE["gold"], width=1, tags="skin")
        if self.corners:
            self._draw_corners(width, height)
        self.canvas.tag_lower("skin")
        self.canvas.itemconfigure(
            self._window, width=max(1, width - 2 * self._padding),
            height=max(1, height - 2 * self._padding))

    def _draw_corners(self, width: int, height: int) -> None:
        """Cuatro florones iguales, girados a su esquina."""
        for corner_x, corner_y, step_x, step_y in (
            (BORDER, BORDER, 1, 1), (width - BORDER, BORDER, -1, 1),
            (BORDER, height - BORDER, 1, -1), (width - BORDER, height - BORDER, -1, -1),
        ):
            self.canvas.create_line(
                corner_x, corner_y + step_y * CORNER,
                corner_x + step_x * CORNER, corner_y,
                fill=PALETTE["gold"], width=2, tags="skin")
            self.canvas.create_oval(
                corner_x + step_x * 4 - 3, corner_y + step_y * 4 - 3,
                corner_x + step_x * 4 + 3, corner_y + step_y * 4 + 3,
                fill=PALETTE["gold"], outline="", tags="skin")


class Banner(tk.Canvas):
    """El rotulo de arriba: titulo grande entre dos filigranas doradas."""

    def __init__(self, parent: tk.Misc, title: str, kicker: str = "",
                 height: int = 96) -> None:
        super().__init__(parent, height=height, highlightthickness=0, bd=0,
                         bg=PALETTE["night"])
        self.title = title
        self.kicker = kicker
        self.bind("<Configure>", self._repaint)

    def set_title(self, title: str) -> None:
        self.title = title
        self._repaint(None)

    def _repaint(self, _event) -> None:
        self.delete("all")
        width = self.winfo_width() or self.winfo_reqwidth()
        middle = (self.winfo_height() or self.winfo_reqheight()) // 2
        if self.kicker:
            self.create_text(0, middle - 30, anchor="w", text=self.kicker,
                             fill=PALETTE["red"], font=FONTS["eyebrow"])
        text = self.create_text(0, middle + 4, anchor="w", text=self.title,
                                fill=PALETTE["gold"], font=FONTS["display"])
        end = self.bbox(text)[2] + SPACE["md"]
        # Una filigrana que sale del titulo y muere en el borde derecho.
        self.create_line(end, middle + 4, width, middle + 4,
                         fill=PALETTE["gold_dark"], width=2)
        self.create_line(end, middle + 10, width - SPACE["xl"], middle + 10,
                         fill=PALETTE["gold_dark"], width=1)
        for offset, radius in ((end, 5), (width - SPACE["xl"], 4)):
            self.create_oval(offset - radius, middle + 4 - radius,
                             offset + radius, middle + 4 + radius,
                             fill=PALETTE["gold"], outline="")


def parchment_text(parent: tk.Misc, **options) -> tk.Text:
    """El area de texto del historial, con aspecto de pagina escrita a mano."""
    widget = tk.Text(parent, wrap="word", state="disabled", relief="flat",
                     bg=PALETTE["paper"], fg=PALETTE["paper_ink"],
                     insertbackground=PALETTE["paper_ink"], font=FONTS["narration"],
                     padx=SPACE["lg"], pady=SPACE["md"], spacing1=3, spacing3=6,
                     selectbackground=PALETTE["gold_dark"], **options)
    widget.tag_configure("narration", foreground=PALETTE["paper_ink"])
    widget.tag_configure("command", foreground=PALETTE["gold_dark"],
                         font=FONTS["narration_bold"])
    widget.tag_configure("notice", foreground=PALETTE["red"],
                         font=FONTS["narration_bold"])
    return widget
