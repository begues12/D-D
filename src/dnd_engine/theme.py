"""El aspecto de la interfaz, en un solo sitio.

Aqui viven los colores, las tipografias y las medidas; ningun otro modulo
escribe un color a mano. Cambiar el aspecto de toda la aplicacion -oscurecerla,
cambiar el dorado por otro acento, agrandar la letra- es tocar `PALETTE`,
`FONTS` o `SPACE`, no buscar hex sueltos por el codigo.

Los widgets `ttk` se configuran con estilos con nombre (`Gold.TButton`,
`Card.TFrame`...). Los que no son `ttk` -las tarjetas del asistente, el lienzo
del mapa- leen `PALETTE` directamente.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .assets import font_family, install_fonts, texture

PALETTE: dict[str, str] = {
    # Fondos, de mas oscuro a mas claro.
    "night": "#15171c",
    "panel": "#1e212a",
    "panel_light": "#272b36",
    "raised": "#31364420",
    # Tinta.
    "ink": "#f2ead7",
    "muted": "#9d947f",
    "faint": "#6c6657",
    # Acentos.
    "gold": "#d6a84f",
    "gold_dark": "#8e6425",
    "red": "#bd6257",
    "green": "#7f9c6a",
    # Lineas y bordes.
    "line": "#343a47",
    # El pergamino de la consola de juego.
    "paper": "#eee3ca",
    "paper_ink": "#2a2520",
}

# Las tres tipografias del juego viajan en `assets/fonts` y se cargan al vuelo;
# si no se pueden, cada una cae en algo que existe en cualquier Windows.
DISPLAY = font_family("Cinzel", "Georgia")            # rotulos e imperiales
HAND = font_family("IM FELL English", "Georgia")      # el pergamino, lo narrado
RUNE = font_family("MedievalSharp", "Georgia")        # pies de ilustracion
UI = "Segoe UI"                                       # lo que hay que leer rapido

FONTS: dict[str, tuple] = {
    "display": (DISPLAY, 30, "bold"),
    "title": (DISPLAY, 18, "bold"),
    "card_title": (DISPLAY, 13, "bold"),
    "kicker": (DISPLAY, 9, "bold"),
    "body": (UI, 10),
    "body_bold": (UI, 10, "bold"),
    "small": (UI, 9),
    "eyebrow": (UI, 9, "bold"),
    "narration": (HAND, 13),
    "narration_bold": (HAND, 13, "bold"),
    "caption": (RUNE, 10),
    "caption_title": (RUNE, 12, "bold"),
    "mono": ("Consolas", 11),
}

# Escala de espaciado: usar estos y no numeros sueltos.
SPACE = {"xs": 4, "sm": 8, "md": 14, "lg": 22, "xl": 34}

# Grosor del anillo de seleccion de una tarjeta.
CARD_BORDER = 2


def apply_theme(root: tk.Misc) -> ttk.Style:
    """Deja listos todos los estilos con nombre. Se llama una vez, al arrancar."""
    install_fonts()
    root.configure(bg=PALETTE["night"])
    style = ttk.Style(root)
    style.theme_use("clam")

    # -- superficies -------------------------------------------------------
    style.configure("App.TFrame", background=PALETTE["night"])
    style.configure("TFrame", background=PALETTE["night"])
    style.configure("Panel.TFrame", background=PALETTE["panel"])
    style.configure("Sunken.TFrame", background=PALETTE["panel_light"])
    style.configure("Card.TLabelframe", background=PALETTE["panel"],
                    foreground=PALETTE["gold"], bordercolor=PALETTE["line"])
    style.configure("Card.TLabelframe.Label", background=PALETTE["panel"],
                    foreground=PALETTE["gold"], font=FONTS["eyebrow"])
    style.configure("Rule.TSeparator", background=PALETTE["line"])

    # -- texto -------------------------------------------------------------
    for name, (background, foreground, font) in {
        "TLabel": ("night", "ink", "body"),
        "Display.TLabel": ("night", "gold", "display"),
        "Title.TLabel": ("night", "gold", "title"),
        "Subtitle.TLabel": ("night", "muted", "body"),
        "Eyebrow.TLabel": ("night", "red", "eyebrow"),
        "Kicker.TLabel": ("panel", "gold", "kicker"),
        "Step.TLabel": ("night", "faint", "eyebrow"),
        "StepOn.TLabel": ("night", "gold", "eyebrow"),
        "Panel.TLabel": ("panel", "ink", "body"),
        "PanelMuted.TLabel": ("panel", "muted", "small"),
        "PanelTitle.TLabel": ("panel", "gold", "card_title"),
        "Stat.TLabel": ("panel_light", "ink", "body_bold"),
    }.items():
        style.configure(name, background=PALETTE[background],
                        foreground=PALETTE[foreground], font=FONTS[font])
    style.configure("Stat.TLabel", padding=SPACE["sm"])

    # -- botones -----------------------------------------------------------
    style.configure("Gold.TButton", background=PALETTE["gold_dark"],
                    foreground=PALETTE["ink"], borderwidth=0, padding=(16, 9),
                    font=FONTS["body_bold"])
    style.map("Gold.TButton",
              background=[("active", PALETTE["gold"]), ("pressed", PALETTE["gold"]),
                          ("disabled", PALETTE["panel_light"])],
              foreground=[("disabled", PALETTE["faint"])])
    style.configure("Tool.TButton", background=PALETTE["panel_light"],
                    foreground=PALETTE["ink"], borderwidth=0, padding=(11, 7),
                    font=FONTS["body"])
    style.map("Tool.TButton",
              background=[("active", PALETTE["gold_dark"]), ("pressed", PALETTE["gold_dark"]),
                          ("disabled", PALETTE["panel"])],
              foreground=[("disabled", PALETTE["faint"])])
    style.configure("Ghost.TButton", background=PALETTE["night"],
                    foreground=PALETTE["muted"], borderwidth=0, padding=(8, 6),
                    font=FONTS["small"])
    style.map("Ghost.TButton",
              background=[("active", PALETTE["night"])],
              foreground=[("active", PALETTE["gold"]), ("disabled", PALETTE["faint"])])

    # -- entradas ----------------------------------------------------------
    # `clam` pinta un relieve claro alrededor de las entradas; se apaga igualando
    # el borde y las luces al fondo, o el campo aparece con un marco blanco.
    for name in ("Dark.TEntry", "Panel.TEntry"):
        style.configure(name, fieldbackground=PALETTE["panel_light"],
                        foreground=PALETTE["ink"], insertcolor=PALETTE["gold"],
                        borderwidth=1, padding=SPACE["sm"],
                        bordercolor=PALETTE["line"], lightcolor=PALETTE["line"],
                        darkcolor=PALETTE["line"])
        style.map(name, bordercolor=[("focus", PALETTE["gold_dark"])],
                  lightcolor=[("focus", PALETTE["gold_dark"])],
                  darkcolor=[("focus", PALETTE["gold_dark"])])
    style.configure("Dark.TCombobox", fieldbackground=PALETTE["panel_light"],
                    background=PALETTE["panel_light"], foreground=PALETTE["ink"],
                    arrowcolor=PALETTE["gold"], borderwidth=1, padding=SPACE["xs"],
                    bordercolor=PALETTE["line"], lightcolor=PALETTE["line"],
                    darkcolor=PALETTE["line"],
                    # En 'readonly' el texto va seleccionado: sin esto sale
                    # blanco sobre azul del sistema.
                    selectbackground=PALETTE["panel_light"],
                    selectforeground=PALETTE["ink"])
    style.map("Dark.TCombobox",
              fieldbackground=[("readonly", PALETTE["panel_light"])],
              foreground=[("readonly", PALETTE["ink"])],
              selectbackground=[("readonly", PALETTE["panel_light"])],
              selectforeground=[("readonly", PALETTE["ink"])],
              bordercolor=[("focus", PALETTE["gold_dark"])])
    style.configure("Dark.TCheckbutton", background=PALETTE["panel"],
                    foreground=PALETTE["ink"], font=FONTS["small"])
    style.map("Dark.TCheckbutton", background=[("active", PALETTE["panel"])],
              foreground=[("active", PALETTE["gold"])])
    style.configure("App.TCheckbutton", background=PALETTE["night"],
                    foreground=PALETTE["ink"], font=FONTS["small"])
    style.map("App.TCheckbutton", background=[("active", PALETTE["night"])],
              foreground=[("active", PALETTE["gold"])])
    style.configure("Gold.Horizontal.TProgressbar", background=PALETTE["gold"],
                    troughcolor=PALETTE["panel_light"], borderwidth=0, thickness=3)
    return style
