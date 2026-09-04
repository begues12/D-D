"""La columna de la derecha: laminas que se van sumando segun avanza la partida.

Cada escena deja una lamina iluminada -emblema, titulo y pie- que se apila
debajo de la anterior, como un cuaderno de viaje que se va llenando. Si algun
dia la IA de turno sabe dibujar, en el mismo hueco va la imagen y lo demas no
cambia.

Los emblemas se dibujan aqui con cuatro trazos de `Canvas`: no hay iconos que
descargar ni que licenciar, y se ven igual de bien a cualquier tamano.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .illustrator import Illustration
from .panels import TexturedPanel
from .theme import FONTS, PALETTE, SPACE

CARD_WIDTH = 232
EMBLEM = 96


def draw_emblem(canvas: tk.Canvas, name: str, x: int, y: int, size: int,
                ink: str, accent: str) -> None:
    """Un simbolo a plumilla, centrado en (x, y)."""
    half = size / 2
    thin, thick = max(1, size // 32), max(2, size // 16)

    if name == "puerta":
        canvas.create_arc(x - half * 0.6, y - half, x + half * 0.6, y + half * 0.2,
                          start=0, extent=180, style="arc", outline=ink, width=thick)
        canvas.create_line(x - half * 0.6, y - half * 0.4, x - half * 0.6, y + half * 0.8,
                           fill=ink, width=thick)
        canvas.create_line(x + half * 0.6, y - half * 0.4, x + half * 0.6, y + half * 0.8,
                           fill=ink, width=thick)
        canvas.create_line(x - half * 0.6, y + half * 0.8, x + half * 0.6, y + half * 0.8,
                           fill=ink, width=thick)
        canvas.create_oval(x + half * 0.2, y + half * 0.1, x + half * 0.35, y + half * 0.25,
                           fill=accent, outline="")
    elif name == "llama":
        canvas.create_polygon(
            x, y - half, x + half * 0.55, y, x + half * 0.3, y + half * 0.7,
            x, y + half * 0.85, x - half * 0.3, y + half * 0.7, x - half * 0.55, y,
            fill="", outline=ink, width=thick, smooth=True)
        canvas.create_polygon(x, y - half * 0.2, x + half * 0.25, y + half * 0.35,
                              x, y + half * 0.6, x - half * 0.25, y + half * 0.35,
                              fill=accent, outline="", smooth=True)
    elif name == "hueso":
        canvas.create_line(x - half * 0.45, y + half * 0.45, x + half * 0.45, y - half * 0.45,
                           fill=ink, width=thick + 3, capstyle="round")
        for end_x, end_y in ((-0.55, 0.55), (0.55, -0.55)):
            # Dos lobulos en cada punta, cruzados al eje del hueso.
            for across_x, across_y in ((-0.16, -0.16), (0.16, 0.16)):
                center_x = x + (end_x + across_x) * half
                center_y = y + (end_y + across_y) * half
                radius = thick + 3
                canvas.create_oval(center_x - radius, center_y - radius,
                                   center_x + radius, center_y + radius,
                                   fill=ink, outline="")
    elif name == "agua":
        for number in range(3):
            offset = (number - 1) * half * 0.45
            canvas.create_line(
                x - half * 0.7, y + offset, x - half * 0.25, y + offset - half * 0.18,
                x + half * 0.25, y + offset + half * 0.18, x + half * 0.7, y + offset,
                fill=ink if number != 1 else accent, width=thick, smooth=True)
    elif name == "arbol":
        canvas.create_line(x, y + half * 0.85, x, y - half * 0.1, fill=ink, width=thick + 1)
        canvas.create_oval(x - half * 0.6, y - half * 0.95, x + half * 0.6, y + half * 0.25,
                           outline=ink, width=thick)
        canvas.create_line(x, y + half * 0.3, x - half * 0.3, y, fill=ink, width=thin)
        canvas.create_line(x, y + half * 0.15, x + half * 0.3, y - half * 0.2,
                           fill=ink, width=thin)
    elif name == "espada":
        canvas.create_line(x, y - half * 0.9, x, y + half * 0.55, fill=ink, width=thick + 1)
        canvas.create_line(x - half * 0.45, y + half * 0.3, x + half * 0.45, y + half * 0.3,
                           fill=ink, width=thick)
        canvas.create_line(x, y + half * 0.55, x, y + half * 0.85, fill=accent, width=thick + 2)
    elif name == "ojo":
        canvas.create_polygon(x - half * 0.85, y, x, y - half * 0.5, x + half * 0.85, y,
                              x, y + half * 0.5, fill="", outline=ink, width=thick,
                              smooth=True)
        canvas.create_oval(x - half * 0.22, y - half * 0.22, x + half * 0.22, y + half * 0.22,
                           outline=ink, width=thin, fill=accent)
    elif name == "moneda":
        canvas.create_oval(x - half * 0.7, y - half * 0.7, x + half * 0.7, y + half * 0.7,
                           outline=ink, width=thick)
        canvas.create_oval(x - half * 0.4, y - half * 0.4, x + half * 0.4, y + half * 0.4,
                           outline=accent, width=thin)
        canvas.create_line(x - half * 0.2, y, x + half * 0.2, y, fill=ink, width=thin)
    elif name == "corona":
        canvas.create_polygon(
            x - half * 0.75, y + half * 0.4, x - half * 0.75, y - half * 0.4,
            x - half * 0.35, y, x, y - half * 0.7, x + half * 0.35, y,
            x + half * 0.75, y - half * 0.4, x + half * 0.75, y + half * 0.4,
            fill="", outline=ink, width=thick)
        canvas.create_line(x - half * 0.75, y + half * 0.4, x + half * 0.75, y + half * 0.4,
                           fill=accent, width=thick)
    else:                                    # luna, y lo que no se reconozca
        canvas.create_oval(x - half * 0.75, y - half * 0.75, x + half * 0.75, y + half * 0.75,
                           outline=ink, width=thick)
        canvas.create_oval(x - half * 0.35, y - half * 0.95, x + half * 0.95, y + half * 0.55,
                           outline="", fill=PALETTE["paper"])
        canvas.create_oval(x - half * 0.35, y - half * 0.95, x + half * 0.95, y + half * 0.55,
                           outline=accent, width=thin)


class Plate(TexturedPanel):
    """Una lamina: el emblema (o la imagen), el titulo y el pie."""

    def __init__(self, parent: tk.Misc, illustration: Illustration) -> None:
        super().__init__(parent, "parchment", padding=SPACE["sm"], corners=True)
        ink, accent = PALETTE["paper_ink"], PALETTE["gold_dark"]
        self.image = None

        if illustration.drawn:
            self.image = tk.PhotoImage(data=illustration.image)
            tk.Label(self.body, image=self.image, bg=PALETTE["paper"],
                     bd=0).pack(pady=(SPACE["sm"], 0))
        else:
            art = tk.Canvas(self.body, height=EMBLEM, bg=PALETTE["paper"],
                            highlightthickness=0, bd=0)
            art.pack(fill="x", pady=(SPACE["sm"], 0))
            art.bind("<Configure>", lambda event, name=illustration.emblem: (
                art.delete("all"),
                draw_emblem(art, name, event.width // 2, EMBLEM // 2,
                            int(EMBLEM * 0.8), ink, accent)))

        title = tk.Label(self.body, text=illustration.title.upper(), bg=PALETTE["paper"],
                         fg=ink, font=FONTS["caption_title"], justify="center")
        title.pack(fill="x", pady=(SPACE["sm"], 0), padx=SPACE["sm"])
        caption = tk.Label(self.body, text=illustration.caption, bg=PALETTE["paper"],
                           fg=ink, font=FONTS["caption"], justify="left")
        caption.pack(fill="x", padx=SPACE["sm"], pady=(SPACE["xs"], SPACE["sm"]))
        for label in (title, caption):
            label.bind("<Configure>", lambda event, one=label: one.configure(
                wraplength=max(80, event.width - SPACE["sm"])))


class ChronicleColumn(ttk.Frame):
    """La pila de laminas, con su propio desplazamiento."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, style="App.TFrame", width=CARD_WIDTH + SPACE["lg"])
        self.grid_propagate(False)
        self.pack_propagate(False)

        header = tk.Canvas(self, height=26, bg=PALETTE["night"],
                           highlightthickness=0, bd=0)
        header.pack(fill="x")
        header.bind("<Configure>", lambda event: self._header(header, event.width))

        self.canvas = tk.Canvas(self, bg=PALETTE["night"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.strip = ttk.Frame(self.canvas, style="App.TFrame")
        self._window = self.canvas.create_window((0, 0), window=self.strip, anchor="nw")
        self.strip.bind("<Configure>", lambda _event: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(
            self._window, width=event.width))
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.plates: list[Plate] = []
        self._empty()

    def _header(self, canvas: tk.Canvas, width: int) -> None:
        canvas.delete("all")
        canvas.create_text(0, 13, anchor="w", text="CRONICA ILUSTRADA",
                           fill=PALETTE["gold"], font=FONTS["eyebrow"])
        canvas.create_line(140, 13, width, 13, fill=PALETTE["gold_dark"], width=1)

    def _empty(self) -> None:
        self._placeholder = ttk.Label(
            self.strip, style="Subtitle.TLabel", wraplength=CARD_WIDTH - SPACE["sm"],
            text="Aqui se iran pintando las escenas segun avance la aventura.")
        self._placeholder.pack(fill="x", padx=SPACE["sm"], pady=SPACE["md"])

    def add(self, illustration: Illustration) -> None:
        if self._placeholder is not None:
            self._placeholder.destroy()
            self._placeholder = None
        plate = Plate(self.strip, illustration)
        plate.configure(height=250)
        plate.pack(fill="x", padx=SPACE["sm"], pady=(0, SPACE["sm"]))
        self.plates.append(plate)
        # La ultima lamina siempre a la vista.
        self.after(60, lambda: self.canvas.yview_moveto(1.0))

    def _wheel(self, event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self:
                self.canvas.yview_scroll(-event.delta // 120, "units")
                return
            widget = getattr(widget, "master", None)
