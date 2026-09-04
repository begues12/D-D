"""Asistente de preparacion: tres pasos hasta empezar a jugar.

    1. La IA         - que casa narra, con que modelo y con que clave.
    2. La aventura   - seis fichas: las escritas a mano y las que invente la IA.
    3. El heroe      - el arquetipo, con lo que trae puesto.
    4. El nombre     - y el resumen de lo elegido.

Cada paso es un metodo que dibuja dentro del mismo lienzo (`_render`), asi que
anadir un paso -el tono, la dificultad, un segundo jugador- es anadirlo a
`STEPS` y escribir su `_step_*`. La navegacion, la barra de progreso y el boton
final no hay que tocarlos.

Todo lo visual sale de `theme.py`: aqui no se escribe ningun color a mano.
"""

from __future__ import annotations

import os
import tkinter as tk
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Callable
from tkinter import messagebox, ttk

from .ai_dm import DungeonMasterError
from .campaign import ARCHETYPES, SCENARIOS, CampaignSetup, PlayerSetup, build_campaign
from .credentials import delete_api_key, load_api_key, save_api_key
from .forge import ScenarioForge
from .providers import PROVIDER_ENV, PROVIDERS, get_provider
from .theme import CARD_BORDER, FONTS, PALETTE, SPACE

# Cuantas aventuras se ensenan a la vez. Las que no cubre el catalogo escrito a
# mano son huecos que rellena la IA.
TOTAL_ADVENTURES = 6
CARD_COLUMNS = 3
# Los arquetipos caben en una sola fila: son pocos y se comparan mejor de un vistazo.
ARCHETYPE_COLUMNS = 4

STEPS = ("LA IA", "LA AVENTURA", "EL HEROE", "EL NOMBRE")
STEP_AI, STEP_ADVENTURE, STEP_HERO, STEP_NAME = range(len(STEPS))


@dataclass
class Adventure:
    """Una ficha del primer paso: del catalogo, inventada, o un hueco por llenar."""

    id: str
    name: str
    description: str
    kicker: str
    intro: str = ""
    pitch: Any = None                      # el gancho, si la propuso la IA
    blueprint: dict[str, Any] | None = None
    empty: bool = False                    # hueco a la espera de que la IA lo llene

    @property
    def forged(self) -> bool:
        return self.pitch is not None

    @classmethod
    def from_catalog(cls, identifier: str, data: dict[str, Any]) -> "Adventure":
        return cls(identifier, data["name"], data["description"], "ESCRITA",
                   intro=data.get("intro", ""))

    @classmethod
    def from_pitch(cls, pitch: Any) -> "Adventure":
        return cls(pitch.id, pitch.name, pitch.description, "INVENTADA",
                   intro=pitch.intro, pitch=pitch)

    @classmethod
    def placeholder(cls, number: int) -> "Adventure":
        return cls(f"hueco-{number}", "Por inventar",
                   "Pulsa 'Que las invente la IA' y aqui aparecera una aventura "
                   "nueva, distinta cada vez.", "IA", empty=True)


class Card(tk.Frame):
    """Ficha pulsable. Se ilumina cuando esta elegida y se apaga si es un hueco."""

    def __init__(self, parent: tk.Misc, kicker: str, title: str, body: str,
                 footer: str = "", on_click: Callable[[], None] | None = None,
                 enabled: bool = True) -> None:
        super().__init__(parent, bg=PALETTE["panel"], highlightthickness=CARD_BORDER,
                         highlightbackground=PALETTE["line"],
                         highlightcolor=PALETTE["line"])
        self.enabled = enabled
        self._on_click = on_click
        self.selected = False

        pad = {"padx": SPACE["md"], "anchor": "w"}
        ink = PALETTE["ink"] if enabled else PALETTE["faint"]
        self._wrapped: list[tk.Label] = []
        self._kicker = tk.Label(self, text=kicker, bg=PALETTE["panel"], font=FONTS["eyebrow"],
                                fg=PALETTE["gold"] if enabled else PALETTE["faint"])
        self._kicker.pack(pady=(SPACE["md"], 0), **pad)
        self._title = tk.Label(self, text=title, bg=PALETTE["panel"], fg=ink,
                               font=FONTS["card_title"], justify="left")
        self._title.pack(pady=(SPACE["xs"], 0), **pad)
        self._wrapped.append(self._title)
        self._body = tk.Label(self, text=body, bg=PALETTE["panel"], fg=PALETTE["muted"],
                              font=FONTS["small"], justify="left")
        self._body.pack(pady=(SPACE["sm"], 0), **pad)
        self._wrapped.append(self._body)
        self._footer = None
        if footer:
            self._footer = tk.Label(self, text=footer, bg=PALETTE["panel"],
                                    fg=PALETTE["faint"], font=FONTS["small"],
                                    justify="left")
            self._footer.pack(pady=(SPACE["sm"], 0), **pad)
            self._wrapped.append(self._footer)
        tk.Frame(self, bg=PALETTE["panel"], height=SPACE["md"]).pack(fill="x")
        self.bind("<Configure>", self._rewrap)

        if enabled and on_click is not None:
            for widget in (self, *self.winfo_children()):
                widget.bind("<Button-1>", lambda _event: self._on_click())
                widget.configure(cursor="hand2")
            self.bind("<Enter>", lambda _event: self._hover(True))
            self.bind("<Leave>", lambda _event: self._hover(False))

    def _rewrap(self, event) -> None:
        """El texto se parte por el ancho real de la ficha, sea cual sea la ventana."""
        width = max(120, event.width - 2 * SPACE["md"] - 2 * CARD_BORDER)
        for label in self._wrapped:
            label.configure(wraplength=width)

    def _hover(self, inside: bool) -> None:
        if self.selected:
            return
        self.configure(highlightbackground=PALETTE["gold_dark"] if inside else PALETTE["line"])

    def select(self, selected: bool) -> None:
        self.selected = selected
        background = PALETTE["panel_light"] if selected else PALETTE["panel"]
        self.configure(highlightbackground=PALETTE["gold"] if selected else PALETTE["line"],
                       bg=background)
        for widget in self.winfo_children():
            widget.configure(bg=background)


class SetupWizard:
    """Pinta la preparacion dentro de un contenedor y avisa cuando hay partida."""

    def __init__(self, parent: tk.Misc, executor: Any,
                 on_play: Callable[[Any, str, bool], None],
                 on_load: Callable[[], None]) -> None:
        self.parent = parent
        self.executor = executor
        self.on_play = on_play
        self.on_load = on_load

        self.step = 0
        self.adventures: list[Adventure] = self._initial_adventures()
        self.adventure: Adventure | None = None
        self.archetype: str | None = None
        self.cards: dict[str, Card] = {}
        self._forge: ScenarioForge | None = None
        self._busy = False

        self.provider = get_provider()
        self.model = self.provider.default_model
        stored = load_api_key(self.provider.id) or self.provider.api_key()

        self.name_var = tk.StringVar(value="Aldric")
        self.hint_var = tk.StringVar(value="")
        self.api_key_var = tk.StringVar(value=stored or "")
        # Con clave, la partida se juega narrada: es como esta pensada.
        self.ai_enabled_var = tk.BooleanVar(value=bool(stored))
        self.remember_key_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="")

        self.frame = ttk.Frame(parent, padding=SPACE["xl"], style="App.TFrame")
        self.frame.pack(fill="both", expand=True)
        self._build_chrome()
        self._render()

    def destroy(self) -> None:
        self.frame.destroy()

    def _initial_adventures(self) -> list[Adventure]:
        written = [Adventure.from_catalog(one, data) for one, data in SCENARIOS.items()]
        written = written[:TOTAL_ADVENTURES]
        holes = TOTAL_ADVENTURES - len(written)
        return written + [Adventure.placeholder(one + 1) for one in range(holes)]

    # -- armazon -----------------------------------------------------------

    def _build_chrome(self) -> None:
        header = ttk.Frame(self.frame, style="App.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="CAMPAIGN BUILDER  /  LOCAL PLAY",
                  style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(header, text="D&D ENGINE", style="Display.TLabel").pack(anchor="w")

        self.steps_frame = ttk.Frame(self.frame, style="App.TFrame")
        self.steps_frame.pack(fill="x", pady=(SPACE["md"], SPACE["xs"]))
        self.step_labels = []
        for number, title in enumerate(STEPS, start=1):
            label = ttk.Label(self.steps_frame, text=f"{number}  {title}", style="Step.TLabel")
            label.pack(side="left", padx=(0, SPACE["lg"]))
            self.step_labels.append(label)

        bar = ttk.Frame(self.frame, style="App.TFrame")
        bar.pack(fill="x", pady=(0, SPACE["lg"]))
        self.segments = []
        for number in range(len(STEPS)):
            segment = tk.Frame(bar, bg=PALETTE["line"], height=3)
            segment.pack(side="left", fill="x", expand=True,
                         padx=(0, SPACE["sm"] if number < len(STEPS) - 1 else 0))
            self.segments.append(segment)

        self.content = ttk.Frame(self.frame, style="App.TFrame")
        self.content.pack(fill="both", expand=True)

        footer = ttk.Frame(self.frame, style="App.TFrame")
        footer.pack(fill="x", pady=(SPACE["lg"], 0))
        ttk.Button(footer, text="Cargar partida guardada", command=self.on_load,
                   style="Ghost.TButton").pack(side="left")
        ttk.Button(footer, text="Borrar clave guardada", command=self.forget_key,
                   style="Ghost.TButton").pack(side="left", padx=(SPACE["sm"], 0))
        self.next_button = ttk.Button(footer, text="Siguiente", command=self.next_step,
                                      style="Gold.TButton")
        self.next_button.pack(side="right")
        self.back_button = ttk.Button(footer, text="Atras", command=self.previous_step,
                                      style="Tool.TButton")
        self.back_button.pack(side="right", padx=(0, SPACE["sm"]))
        ttk.Label(footer, textvariable=self.status_var,
                  style="Subtitle.TLabel").pack(side="right", padx=(0, SPACE["md"]))

    def _render(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        self.cards.clear()
        for number, label in enumerate(self.step_labels):
            label.configure(style="StepOn.TLabel" if number == self.step else "Step.TLabel")
        for number, segment in enumerate(self.segments):
            segment.configure(bg=PALETTE["gold"] if number <= self.step else PALETTE["line"])
        (self._step_ai, self._step_adventure, self._step_archetype,
         self._step_name)[self.step]()
        self.back_button.state(["disabled"] if self.step == 0 else ["!disabled"])
        self.next_button.configure(
            text="Empezar partida" if self.step == len(STEPS) - 1 else "Siguiente")

    # -- paso 1: la IA -----------------------------------------------------

    def _step_ai(self) -> None:
        self._heading("Con que IA vas a jugar?",
                      "El DM interpreta lo que escribes, narra lo que pasa y se "
                      "inventa las aventuras. Sin clave se juega con comandos.")
        self._provider_cards()
        self._model_cards()
        # El hueco que sobra empuja la clave abajo, en vez de estirar las fichas.
        ttk.Frame(self.content, style="App.TFrame").pack(fill="both", expand=True)
        self._key_panel()

    def _provider_cards(self) -> None:
        row = ttk.Frame(self.content, style="App.TFrame")
        row.pack(fill="x", pady=(0, SPACE["md"]))
        for number, provider in enumerate(PROVIDERS.values()):
            row.columnconfigure(number, weight=1, uniform="provider")
            card = Card(row, "CASA", provider.name,
                        f"{len(provider.models)} modelos  ·  {provider.env_var}",
                        on_click=(lambda one=provider: self.choose_provider(one)))
            card.grid(row=0, column=number, sticky="nsew",
                      padx=SPACE["sm"], pady=SPACE["sm"])
            self.cards[provider.id] = card
            card.select(provider.id == self.provider.id)

    def _model_cards(self) -> None:
        grid = ttk.Frame(self.content, style="App.TFrame")
        grid.pack(fill="x")
        models = self.provider.models
        for column in range(max(1, len(models))):
            grid.columnconfigure(column, weight=1, uniform="model")
        if not models:
            ttk.Label(grid, style="Subtitle.TLabel",
                      text=f"{self.provider.name} no tiene modelos declarados.").pack(
                anchor="w")
            return
        for number, model in enumerate(models):
            card = Card(grid, model.price, model.name, model.note,
                        footer=model.id,
                        on_click=(lambda one=model: self.choose_model(one.id)))
            card.grid(row=0, column=number, sticky="nsew",
                      padx=SPACE["sm"], pady=SPACE["sm"])
            self.cards[model.id] = card
            card.select(model.id == self.model)

    def _key_panel(self) -> None:
        panel = ttk.Frame(self.content, style="Panel.TFrame", padding=SPACE["md"])
        panel.pack(fill="x", pady=(SPACE["md"], 0))
        panel.columnconfigure(1, weight=1)
        ttk.Label(panel, text=f"Clave de {self.provider.name}",
                  style="Panel.TLabel").grid(row=0, column=0, sticky="w",
                                             padx=(0, SPACE["md"]))
        ttk.Entry(panel, textvariable=self.api_key_var, style="Panel.TEntry",
                  show="*").grid(row=0, column=1, sticky="ew")
        options = ttk.Frame(panel, style="Panel.TFrame")
        options.grid(row=1, column=1, sticky="w", pady=(SPACE["sm"], 0))
        ttk.Checkbutton(options, text="Recordar la clave en este equipo",
                        variable=self.remember_key_var,
                        style="Dark.TCheckbutton").pack(side="left")
        ttk.Checkbutton(options, text="Narrar con el DM de IA",
                        variable=self.ai_enabled_var,
                        style="Dark.TCheckbutton").pack(side="left", padx=(SPACE["md"], 0))
        ttk.Label(panel, style="PanelMuted.TLabel",
                  text=f"Se guarda cifrada en este equipo, nunca en la partida. "
                       f"Tambien vale la variable {self.provider.env_var}.").grid(
            row=2, column=1, sticky="w", pady=(SPACE["sm"], 0))

    def choose_provider(self, provider: Any) -> None:
        if provider.id == self.provider.id:
            return
        self.provider = provider
        self.model = provider.default_model
        self._load_key()
        self._forge = None                 # el cliente anterior ya no sirve
        self._render()

    def choose_model(self, identifier: str) -> None:
        self.model = identifier
        self._forge = None
        for one, card in self.cards.items():
            if self.provider.model_info(one) is not None:
                card.select(one == identifier)

    def _load_key(self) -> None:
        stored = load_api_key(self.provider.id) or self.provider.api_key() or ""
        self.api_key_var.set(stored)
        self.ai_enabled_var.set(bool(stored))

    # -- paso 2: la aventura -----------------------------------------------

    def _step_adventure(self) -> None:
        self._heading("Que vais a jugar?",
                      "Las escritas a mano estan siempre; las de la IA cambian cada vez "
                      "que se las pides.")
        grid = ttk.Frame(self.content, style="App.TFrame")
        grid.pack(fill="both", expand=True)
        for column in range(CARD_COLUMNS):
            grid.columnconfigure(column, weight=1, uniform="adventure")
        for row in range((len(self.adventures) + CARD_COLUMNS - 1) // CARD_COLUMNS):
            grid.rowconfigure(row, weight=1, uniform="adventure-row")

        for number, adventure in enumerate(self.adventures):
            card = Card(
                grid, adventure.kicker, adventure.name, adventure.description,
                footer=adventure.intro if adventure.forged else "",
                on_click=(lambda one=adventure: self.choose_adventure(one)),
                enabled=not adventure.empty,
            )
            card.grid(row=number // CARD_COLUMNS, column=number % CARD_COLUMNS,
                      sticky="nsew", padx=SPACE["sm"], pady=SPACE["sm"])
            self.cards[adventure.id] = card
            card.select(self.adventure is not None and self.adventure.id == adventure.id)

        self._forge_panel()

    def _forge_panel(self) -> None:
        panel = ttk.Frame(self.content, style="Panel.TFrame", padding=SPACE["md"])
        panel.pack(fill="x", pady=(SPACE["md"], 0))
        panel.columnconfigure(1, weight=1)

        ttk.Label(panel, text="De que quereis que vayan las inventadas",
                  style="Panel.TLabel").grid(row=0, column=0, sticky="w",
                                             padx=(0, SPACE["md"]))
        ttk.Entry(panel, textvariable=self.hint_var, style="Panel.TEntry").grid(
            row=0, column=1, sticky="ew")
        self.invent_button = ttk.Button(panel, text="Que las invente la IA",
                                        command=self.invent, style="Tool.TButton")
        self.invent_button.grid(row=0, column=2, padx=(SPACE["sm"], 0))

        ttk.Label(panel, style="PanelMuted.TLabel",
                  text=f"Las inventa {self.provider.name} con {self.model}.").grid(
            row=1, column=1, sticky="w", pady=(SPACE["sm"], 0))

    def choose_adventure(self, adventure: Adventure) -> None:
        if self._busy:
            return
        self.adventure = adventure
        for identifier, card in self.cards.items():
            card.select(identifier == adventure.id)

    def invent(self) -> None:
        """Rellena los huecos con aventuras nuevas. Una llamada, varias ideas."""
        forge = self._ready_forge()
        if forge is None:
            return
        # Se piden tantas como huecos queden; si ya no hay, se renuevan las
        # inventadas y las escritas a mano se quedan donde estan.
        empty = sum(1 for one in self.adventures if one.empty)
        holes = empty or sum(1 for one in self.adventures if one.forged) or 1
        avoid = tuple(one.name for one in self.adventures if one.forged)
        self._working(f"Pensando {holes} aventuras...")
        future = self.executor.submit(
            forge.propose, holes, self.hint_var.get().strip(), 1, avoid)
        self._await(future, self._fill_holes)

    def _fill_holes(self, pitches) -> None:
        """Las nuevas ocupan los huecos, y si no hay, sustituyen a las inventadas."""
        self._working(None)
        replaceable = [number for number, one in enumerate(self.adventures)
                       if one.empty or one.forged]
        for position, pitch in zip(replaceable, pitches):
            self.adventures[position] = Adventure.from_pitch(pitch)
        if self.adventure is not None and self.adventure.id not in {
                one.id for one in self.adventures}:
            self.adventure = None
        self._render()

    def _ready_forge(self) -> ScenarioForge | None:
        self.remember_ai()
        if self._forge is not None:
            return self._forge
        try:
            self._forge = ScenarioForge(provider=self.provider, model=self.model)
        except DungeonMasterError as error:
            messagebox.showerror("No puedo inventar aventuras", str(error))
            return None
        return self._forge

    # -- paso 2: el heroe --------------------------------------------------

    def _step_archetype(self) -> None:
        self._heading("A quien llevas?",
                      "Solo cambia con que empiezas: el motor no reparte clases.")
        grid = ttk.Frame(self.content, style="App.TFrame")
        grid.pack(fill="both", expand=True)
        columns = min(ARCHETYPE_COLUMNS, len(ARCHETYPES))
        for column in range(columns):
            grid.columnconfigure(column, weight=1, uniform="archetype")
        for row in range((len(ARCHETYPES) + columns - 1) // columns):
            grid.rowconfigure(row, weight=1, uniform="archetype-row")

        for number, (identifier, archetype) in enumerate(ARCHETYPES.items()):
            card = Card(
                grid, f"{archetype.max_hp} HP  ·  CA {archetype.armor_class}",
                archetype.name, archetype.description,
                footer=self._archetype_kit(archetype),
                on_click=(lambda one=identifier: self.choose_archetype(one)),
            )
            card.grid(row=number // columns, column=number % columns,
                      sticky="nsew", padx=SPACE["sm"], pady=SPACE["sm"])
            self.cards[identifier] = card
            card.select(identifier == self.archetype)

    def _archetype_kit(self, archetype: Any) -> str:
        weapon = archetype.weapon
        lines = [f"{weapon['name']} ({weapon.get('damage', '1d8')})"]
        if archetype.spells:
            lines.append("Hechizos: " + ", ".join(one["name"] for one in archetype.spells))
        lines.append(", ".join(one["name"] for one in archetype.items))
        return "\n".join(lines)

    def choose_archetype(self, identifier: str) -> None:
        self.archetype = identifier
        for one, card in self.cards.items():
            card.select(one == identifier)

    # -- paso 3: el nombre -------------------------------------------------

    def _step_name(self) -> None:
        self._heading("Como se llama?", "Lo ultimo, y ya estais dentro.")
        row = ttk.Frame(self.content, style="App.TFrame")
        row.pack(fill="x")
        entry = ttk.Entry(row, textvariable=self.name_var, style="Dark.TEntry",
                          font=FONTS["title"], width=26)
        entry.pack(anchor="w")
        entry.focus_set()
        entry.bind("<Return>", lambda _event: self.next_step())
        entry.bind("<KeyRelease>", lambda _event: self._refresh_summary())

        panel = ttk.Frame(self.content, style="Panel.TFrame", padding=SPACE["lg"])
        panel.pack(fill="both", expand=True, pady=(SPACE["lg"], 0))
        adventure = self.adventure
        archetype = ARCHETYPES[self.archetype] if self.archetype else None

        ttk.Label(panel, text="LO QUE VAIS A JUGAR", style="PanelMuted.TLabel").pack(anchor="w")
        ttk.Label(panel, text=adventure.name if adventure else "-",
                  style="PanelTitle.TLabel").pack(anchor="w", pady=(SPACE["sm"], 0))
        intro = ttk.Label(panel, style="Panel.TLabel", justify="left",
                          text=(adventure.intro or adventure.description) if adventure else "")
        intro.pack(anchor="w", fill="x", pady=(SPACE["sm"], 0))
        # El gancho se parte por el ancho real del panel, no por un numero fijo.
        panel.bind("<Configure>", lambda event: intro.configure(
            wraplength=max(240, event.width - 3 * SPACE["lg"])))

        ttk.Separator(panel, style="Rule.TSeparator").pack(
            fill="x", pady=(SPACE["lg"], SPACE["md"]))
        if archetype is not None:
            weapon = archetype.weapon
            self.summary_name = ttk.Label(panel, style="PanelTitle.TLabel", text="")
            self.summary_name.pack(anchor="w")
            ttk.Label(panel, style="Panel.TLabel",
                      text=f"{archetype.max_hp} HP  ·  CA {archetype.armor_class}  ·  "
                           f"{weapon['name']} ({weapon.get('damage', '1d8')})").pack(
                anchor="w", pady=(SPACE["xs"], 0))
            self._refresh_summary()
        narrator = (f"{self.provider.name} · {self.model}"
                    if self.ai_enabled_var.get() else "no (comandos de siempre)")
        ttk.Label(panel, text=f"DM con IA: {narrator}",
                  style="PanelMuted.TLabel").pack(anchor="w", pady=(SPACE["sm"], 0))

    def _refresh_summary(self) -> None:
        """El resumen se rehace al escribir, para ver el nombre en su sitio."""
        if self.step != len(STEPS) - 1 or self.archetype is None:
            return
        self.summary_name.configure(
            text=f"{self.name_var.get().strip() or 'Sin nombre'}, "
                 f"{ARCHETYPES[self.archetype].name.lower()}")

    # -- navegacion --------------------------------------------------------

    def next_step(self) -> None:
        if self._busy:
            return
        problem = self._missing()
        if problem:
            self.status_var.set(problem)
            return
        if (self.step == STEP_ADVENTURE and self.adventure.forged
                and self.adventure.blueprint is None):
            self.build_adventure()          # avanza el solo cuando termine
            return
        if self.step == STEP_NAME:
            self.play()
            return
        self.status_var.set("")
        self.step += 1
        self._render()

    def _missing(self) -> str:
        """Que falta para poder pasar de este paso. Vacio si no falta nada."""
        if self.step == STEP_AI:
            if self.ai_enabled_var.get() and not self.api_key_var.get().strip():
                return f"Escribe la clave de {self.provider.name}, o quita el DM con IA."
            if not self.model:
                return "Elige un modelo."
        if self.step == STEP_ADVENTURE and self.adventure is None:
            return "Elige una aventura."
        if self.step == STEP_HERO and self.archetype is None:
            return "Elige un arquetipo."
        return ""

    def previous_step(self) -> None:
        if self._busy or self.step == 0:
            return
        self.status_var.set("")
        self.step -= 1
        self._render()

    def build_adventure(self) -> None:
        """Monta el mundo de la aventura inventada, justo antes de necesitarlo."""
        forge = self._ready_forge()
        if forge is None:
            return
        adventure = self.adventure
        self._working(f"Montando '{adventure.name}'...")
        future = self.executor.submit(forge.build, adventure.pitch,
                                      self.hint_var.get().strip())

        def ready(blueprint: dict) -> None:
            self._working(None)
            adventure.blueprint = blueprint
            adventure.name = blueprint.get("name", adventure.name)
            self.step += 1
            self._render()

        self._await(future, ready)

    def play(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            self.status_var.set("Hace falta un nombre.")
            return
        self.remember_ai()
        setup = CampaignSetup(
            players=[PlayerSetup(name, self.archetype)],
            scenario=self.adventure.id,
            blueprint=self.adventure.blueprint,
            use_ai_dm=self.ai_enabled_var.get(),
            ai_provider=self.provider.id,
            ai_model=self.model,
        )
        try:
            engine = build_campaign(setup)
        except ValueError as error:
            messagebox.showerror("No se puede empezar", str(error))
            return
        self.on_play(engine, setup.players[0].id, self.ai_enabled_var.get())

    # -- credenciales y espera ---------------------------------------------

    def remember_ai(self) -> None:
        """Deja la clave a mano del SDK y, si lo piden, guardada en el equipo."""
        os.environ[PROVIDER_ENV] = self.provider.id
        key = self.api_key_var.get().strip()
        if not key:
            return
        self.provider.use_key(key)
        if self.remember_key_var.get():
            save_api_key(key, self.provider.id)
        else:
            delete_api_key(self.provider.id)

    def forget_key(self) -> None:
        delete_api_key(self.provider.id)
        self.api_key_var.set("")
        self.ai_enabled_var.set(False)
        self.provider.forget_key()
        self.status_var.set(f"Clave de {self.provider.name} borrada de este equipo.")

    def _working(self, message: str | None) -> None:
        """Bloquea la navegacion mientras la IA piensa, sin congelar la ventana."""
        self._busy = message is not None
        self.status_var.set(message or "")
        state = ["disabled"] if self._busy else ["!disabled"]
        self.next_button.state(state)
        if hasattr(self, "invent_button"):
            self.invent_button.state(state)

    def _await(self, future: Future, callback: Callable[[Any], None]) -> None:
        if not future.done():
            self.frame.after(80, lambda: self._await(future, callback))
            return
        try:
            callback(future.result())
        except (DungeonMasterError, ValueError) as error:
            self._working(None)
            messagebox.showerror("La IA no ha podido", str(error))

    # -- utilidades --------------------------------------------------------

    def _heading(self, title: str, subtitle: str) -> None:
        ttk.Label(self.content, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.content, text=subtitle, style="Subtitle.TLabel").pack(
            anchor="w", pady=(SPACE["xs"], SPACE["md"]))
