"""Interfaz grafica local y ligera para probar el motor sin terminal.

La ventana tiene dos caras: el asistente de preparacion (`wizard.py`), que
elige aventura, heroe y nombre, y la sala de juego, que es la consola de
siempre con mapa, panel y un historial en pergamino. Los colores y las medidas
salen de `theme.py`.
"""

from __future__ import annotations

import io
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .ai_dm import DungeonMasterError
from .campaign import CampaignSetup
from .console import Console
from .persistence import load_game, save_game
from .chronicle import ChronicleColumn
from .illustrator import Illustrator, scene_of, should_illustrate
from .panels import Banner, TexturedPanel, parchment_text
from .theme import FONTS, PALETTE, SPACE, apply_theme
from .wizard import SetupWizard


class GameWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("D&D Engine")
        self.root.geometry("1120x740")
        self.root.minsize(820, 560)
        apply_theme(self.root)
        self.console: Console | None = None
        self.ai_enabled_var = tk.BooleanVar(value=False)
        self._illustrator: Illustrator | None = None
        self._events_seen = 0
        self.output_buffer = io.StringIO()
        self.output_position = 0
        self._typing_queue: list[tuple[str, str]] = []
        self._typing = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dnd-engine")
        self._busy = False
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.wizard = SetupWizard(self.root, self._executor, self.start_game, self.load_game)

    def start_game(self, engine, player_id: str, ai_enabled: bool) -> None:
        """Lo que devuelve el asistente cuando la campana esta lista."""
        self.ai_enabled_var.set(ai_enabled)
        self._open_game(engine, player_id)

    def load_game(self) -> None:
        path = filedialog.askopenfilename(
            title="Cargar partida", filetypes=[("Partidas D&D", "*.json"), ("Todos", "*")]
        )
        if not path:
            return
        try:
            engine = load_game(path)
            setup = CampaignSetup.from_world(engine.world.world)
            player_id = setup.players[0].id if setup else next(iter(engine.world.world.characters))
        except (OSError, ValueError, KeyError, StopIteration) as error:
            messagebox.showerror("No se puede cargar", str(error))
            return
        self.wizard.remember_ai()
        self.ai_enabled_var.set(bool(setup and setup.use_ai_dm))
        self._open_game(engine, player_id)

    def _open_game(self, engine, player_id: str) -> None:
        self.wizard.destroy()
        self.output_buffer = io.StringIO()
        self.output_position = 0
        self.console = Console(engine, player_id, stream_out=self.output_buffer)
        self.console.narrator = self.ai_enabled_var.get()
        self._build_game_screen()
        self._events_seen = len(engine.events.history)
        self._set_busy(True, "El DM esta preparando la escena...")
        self._append("El DM esta preparando la escena...")
        future = self._executor.submit(self.console.opening)
        self._poll_future(future, self._finish_opening)

    def _build_game_screen(self) -> None:
        self.game_frame = ttk.Frame(self.root, padding=SPACE["md"], style="App.TFrame")
        self.game_frame.pack(fill="both", expand=True)

        header = ttk.Frame(self.game_frame, style="App.TFrame")
        header.pack(fill="x", pady=(0, SPACE["md"]))
        self.campaign_var = tk.StringVar()
        self.location_var = tk.StringVar()
        self.banner = Banner(header, "", kicker="SALA DE JUEGO", height=64)
        self.banner.pack(side="left", fill="x", expand=True)
        toolbar = ttk.Frame(header, style="App.TFrame")
        toolbar.pack(side="right", padx=(SPACE["md"], 0))
        ttk.Button(toolbar, text="Guardar", command=self.save_game,
                   style="Tool.TButton").pack(side="right")
        self.ai_status_var = tk.StringVar(
            value="DM IA: activo" if self.ai_enabled_var.get() else "DM IA: apagado")
        ttk.Checkbutton(toolbar, textvariable=self.ai_status_var,
                        variable=self.ai_enabled_var, command=self.toggle_ai,
                        style="App.TCheckbutton").pack(side="right", padx=(0, SPACE["md"]))

        content = ttk.Frame(self.game_frame, style="App.TFrame")
        content.pack(fill="both", expand=True)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        self._build_sidebar(content)
        self._build_play_area(content)
        self.chronicle = ChronicleColumn(content)
        self.chronicle.grid(row=0, column=2, sticky="ns", padx=(SPACE["md"], 0))

    def _build_sidebar(self, content: ttk.Frame) -> None:
        sidebar = ttk.Frame(content, width=228, style="App.TFrame")
        sidebar.grid(row=0, column=0, sticky="ns", padx=(0, SPACE["md"]))
        sidebar.grid_propagate(False)
        sidebar.pack_propagate(False)

        character = TexturedPanel(sidebar, "leather")
        character.configure(height=150)
        character.pack(fill="x")
        self.character_var = tk.StringVar()
        self.hp_var = tk.StringVar()
        tk.Label(character.body, text="TU PERSONAJE", bg=PALETTE["panel"],
                 fg=PALETTE["gold"], font=FONTS["kicker"]).pack(anchor="w")
        tk.Label(character.body, textvariable=self.character_var, bg=PALETTE["panel"],
                 fg=PALETTE["ink"], font=FONTS["card_title"]).pack(anchor="w",
                                                                   pady=(SPACE["sm"], 0))
        tk.Label(character.body, textvariable=self.hp_var, bg=PALETTE["panel_light"],
                 fg=PALETTE["ink"], font=FONTS["body_bold"], pady=SPACE["xs"]).pack(
            fill="x", pady=(SPACE["sm"], SPACE["xs"]))
        tk.Label(character.body, textvariable=self.location_var, bg=PALETTE["panel"],
                 fg=PALETTE["muted"], font=FONTS["small"], wraplength=170,
                 justify="left").pack(anchor="w")

        tools = TexturedPanel(sidebar, "leather")
        tools.pack(fill="both", expand=True, pady=(SPACE["md"], 0))
        tk.Label(tools.body, text="ACCIONES", bg=PALETTE["panel"], fg=PALETTE["gold"],
                 font=FONTS["kicker"]).pack(anchor="w", pady=(0, SPACE["sm"]))
        for label, command in (
            ("Mirar", "mirar"), ("Mapa", "mapa"), ("Estado", "estado"),
            ("Inventario", "inventario"), ("Ayuda", "ayuda"), ("Pasar turno", "turno"),
        ):
            ttk.Button(tools.body, text=label, style="Tool.TButton",
                       command=lambda value=command: self.submit(value)).pack(
                fill="x", pady=2)

    def _build_play_area(self, content: ttk.Frame) -> None:
        play_area = ttk.Frame(content, style="App.TFrame")
        play_area.grid(row=0, column=1, sticky="nsew")
        play_area.columnconfigure(0, weight=1)
        # El mapa mide lo que pide; el pergamino es el que se estira.
        play_area.rowconfigure(0, weight=0, minsize=320)
        play_area.rowconfigure(1, weight=1)

        board = TexturedPanel(play_area, "wood", padding=SPACE["sm"])
        board.grid(row=0, column=0, sticky="nsew", pady=(0, SPACE["md"]))
        self.scene_title_var = tk.StringVar()
        tk.Label(board.body, textvariable=self.scene_title_var, bg=PALETTE["panel"],
                 fg=PALETTE["gold"], font=FONTS["card_title"]).pack(anchor="w",
                                                                    pady=(0, SPACE["xs"]))
        self.scene_canvas = tk.Canvas(board.body, bg=PALETTE["night"], bd=0,
                                      highlightthickness=0)
        self.scene_canvas.pack(fill="both", expand=True)
        self.scene_canvas.bind("<Configure>", lambda _event: self._draw_scene())

        self.roster = tk.Frame(board.body, bg=PALETTE["panel"])
        self.roster.pack(fill="x", pady=(SPACE["sm"], 0))

        page = TexturedPanel(play_area, "parchment", padding=SPACE["sm"], corners=True)
        page.grid(row=1, column=0, sticky="nsew")
        self.history = parchment_text(page.body, height=8)
        self.history.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(page.body, orient="vertical", command=self.history.yview)
        scrollbar.pack(side="right", fill="y")
        self.history.configure(yscrollcommand=scrollbar.set)

        bottom = ttk.Frame(self.game_frame, style="App.TFrame")
        bottom.pack(fill="x", pady=(10, 0))
        self.busy_var = tk.StringVar()
        ttk.Label(bottom, textvariable=self.busy_var, style="Subtitle.TLabel").pack(side="left", padx=(0, 12))
        self.command_var = tk.StringVar()
        self.command_entry = ttk.Entry(bottom, textvariable=self.command_var, style="Dark.TEntry")
        self.command_entry.pack(side="left", fill="x", expand=True)
        self.command_entry.bind("<Return>", lambda _event: self.submit())
        self.send_button = ttk.Button(bottom, text="Enviar", command=self.submit, style="Gold.TButton")
        self.send_button.pack(side="left", padx=(8, 0))
        self.command_entry.focus_set()
        self._refresh_panel()
        self._draw_scene()

    def _refresh_panel(self) -> None:
        if self.console is None:
            return
        actor = self.console.engine.world.get_character(self.console.actor_id)
        location = self.console.engine.world.location_of(actor.id)
        setup = CampaignSetup.from_world(self.console.engine.world.world)
        title = setup.campaign_title if setup else self.console.engine.world.world.name
        self.campaign_var.set(title)
        self.banner.set_title(title)
        self.character_var.set(f"{actor.name}  ·  nivel {actor.level}")
        self.hp_var.set(f"HP  {actor.hp} / {actor.max_hp}")
        self.location_var.set(location.name if location else "Ubicacion desconocida")
        self._refresh_roster(location)

    # -- quien hay delante -------------------------------------------------

    def _refresh_roster(self, location) -> None:
        """Una ficha por criatura presente: vida, estado y de quien es el turno."""
        if not hasattr(self, "roster"):
            return
        for child in self.roster.winfo_children():
            child.destroy()
        if location is None:
            return
        engine = self.console.engine
        encounter = engine.encounter
        turn_of = (encounter.order[encounter.current_index]
                   if encounter is not None and encounter.order else None)
        if turn_of is not None:
            tk.Label(self.roster, bg=PALETTE["panel"], fg=PALETTE["red"],
                     font=FONTS["kicker"],
                     text=f"COMBATE  ·  RONDA {encounter.round_number}  ·  "
                          f"TURNO DE {engine.world.get_character(turn_of).name.upper()}"
                     ).pack(anchor="w", pady=(0, SPACE["xs"]))

        strip = tk.Frame(self.roster, bg=PALETTE["panel"])
        strip.pack(fill="x")
        for character_id in sorted(location.occupants):
            character = engine.world.get_character(character_id)
            self._roster_pill(strip, character, character_id == turn_of,
                              character_id == self.console.actor_id)

    def _roster_pill(self, parent: tk.Frame, character, is_turn: bool, is_you: bool) -> None:
        background = PALETTE["panel_light"] if is_turn else PALETTE["panel"]
        pill = tk.Frame(parent, bg=background, highlightthickness=1, bd=0,
                        highlightbackground=PALETTE["gold"] if is_turn else PALETTE["line"])
        pill.pack(side="left", padx=(0, SPACE["sm"]), pady=2)

        color = (PALETTE["gold"] if is_you else
                 PALETTE["red"] if type(character).__name__ == "Enemy" else PALETTE["ink"])
        tk.Label(pill, text=character.name, bg=background, fg=color,
                 font=FONTS["body_bold"]).pack(anchor="w", padx=SPACE["sm"],
                                               pady=(SPACE["xs"], 0))

        bar = tk.Canvas(pill, width=118, height=6, bg=background, bd=0,
                        highlightthickness=0)
        bar.pack(anchor="w", padx=SPACE["sm"], pady=(3, 0))
        share = 0 if character.max_hp <= 0 else max(0.0, character.hp / character.max_hp)
        bar.create_rectangle(0, 0, 118, 6, fill=PALETTE["night"], outline="")
        if share > 0:
            # Verde, dorado o rojo: se ve de un vistazo lo que queda.
            fill = (PALETTE["green"] if share > 0.5 else
                    PALETTE["gold"] if share > 0.25 else PALETTE["red"])
            bar.create_rectangle(0, 0, int(118 * share), 6, fill=fill, outline="")

        tk.Label(pill, text=self._state_line(character), bg=background,
                 fg=PALETTE["muted"], font=FONTS["small"]).pack(
            anchor="w", padx=SPACE["sm"], pady=(2, SPACE["xs"]))

    def _state_line(self, character) -> str:
        if character.is_dead:
            return "muerto"
        if character.is_dying:
            saves = character.death_saves
            return f"agonizando  {saves.successes}/{saves.failures}"
        state = ", ".join(sorted(one.value for one in character.conditions))
        return f"{character.hp}/{character.max_hp} hp" + (f"  ·  {state}" if state else "")

    def submit(self, command: str | None = None) -> None:
        if self.console is None or self._busy:
            return
        value = (command if command is not None else self.command_var.get()).strip()
        if not value:
            return
        if command is None:
            self.command_var.set("")
        self._append(f"> {value}")
        self._set_busy(True, "El DM esta pensando..." if self.console.narrator else "Procesando...")
        future = self._executor.submit(self.console.handle, value)
        self._poll_future(future, self._finish_command)

    def _poll_future(self, future: Future, callback) -> None:
        if future.done():
            try:
                callback(future.result())
            except Exception as error:
                self._append(f"[!] No se pudo completar la accion: {error}")
                self._finish_waiting()
            return
        self.root.after(50, lambda: self._poll_future(future, callback))

    def _finish_opening(self, opening: str) -> None:
        self._append_new_console_output()
        self._append(opening)
        self._finish_waiting()
        self.illustrate(opening)

    def _finish_command(self, _result) -> None:
        self._append_new_console_output()
        self._refresh_panel()
        self._animate_latest_movement()
        self._finish_waiting()
        events = self.console.engine.events.history[self._events_seen:]
        self._events_seen = len(self.console.engine.events.history)
        if should_illustrate(events):
            self.illustrate()

    # -- cronica ilustrada -------------------------------------------------

    def illustrate(self, narration: str = "") -> None:
        """Pinta la escena actual. Con IA se la pide; sin ella, la saca del motor."""
        if self.console is None:
            return
        engine, actor = self.console.engine, self.console.actor_id
        illustrator = self._ready_illustrator()
        if illustrator is None:
            self.chronicle.add(scene_of(engine, actor))
            return
        future = self._executor.submit(illustrator.illustrate, engine, actor, narration)
        self._poll_illustration(future, scene_of(engine, actor))

    def _ready_illustrator(self) -> Illustrator | None:
        """La IA solo ilustra si esta encendida y hay clave; si no, no se molesta."""
        if not self.ai_enabled_var.get() or not self.wizard.provider.is_configured():
            return None
        if self._illustrator is None:
            try:
                self._illustrator = Illustrator(provider=self.wizard.provider,
                                                model=self.wizard.model)
            except DungeonMasterError:
                return None
        return self._illustrator

    def _poll_illustration(self, future: Future, fallback) -> None:
        """La lamina llega cuando llega: no bloquea el turno ni la ventana."""
        if not future.done():
            self.root.after(120, lambda: self._poll_illustration(future, fallback))
            return
        try:
            self.chronicle.add(future.result())
        except Exception:
            # Una lamina no vale un error en pantalla: se pone la del motor.
            self.chronicle.add(fallback)

    def _draw_scene(self, marker=None) -> None:
        if not hasattr(self, "scene_canvas") or self.console is None:
            return
        canvas = self.scene_canvas
        canvas.delete("all")
        location = self.console.engine.world.location_of(self.console.actor_id)
        self.scene_title_var.set(f"{location.name.upper()}  /  {location.id}")
        grid = location.grid
        if grid is None:
            canvas.create_text(20, 35, anchor="w", text="Teatro de la mente",
                               fill=PALETTE["gold"], font=FONTS["title"])
            canvas.create_text(20, 68, anchor="w", width=max(200, canvas.winfo_width() - 40),
                               text=location.description or "La sala no tiene cuadricula.",
                               fill=PALETTE["ink"], font=FONTS["narration"])
            self._draw_doors(canvas, location, None, 20, 115)
            return
        width = canvas.winfo_width() or canvas.winfo_reqwidth()
        height = canvas.winfo_height() or canvas.winfo_reqheight()
        # La casilla se ajusta al hueco por los dos lados: asi la cuadricula
        # entera cabe siempre, y el tablero queda centrado.
        cell = max(22, min(62, min((width - 32) // max(grid.width, 1),
                                   (height - 32) // max(grid.height, 1))))
        origin_x = max(16, (width - cell * grid.width) // 2)
        origin_y = max(16, (height - cell * grid.height) // 2)
        for y in range(grid.height):
            for x in range(grid.width):
                px, py = origin_x + x * cell, origin_y + y * cell
                fill = "#343943" if (x, y) not in grid.blocked else "#111318"
                canvas.create_rectangle(px, py, px + cell - 2, py + cell - 2, fill=fill, outline="#4b505c")
                if (x, y) in grid.blocked:
                    canvas.create_line(px + 8, py + 8, px + cell - 10, py + cell - 10, fill="#71624c", width=2)
                    canvas.create_line(px + cell - 10, py + 8, px + 8, py + cell - 10, fill="#71624c", width=2)
        for item in location.items:
            if item.cell is not None:
                self._draw_token(canvas, item.cell, origin_x, origin_y, cell, "#d6a84f", "◆")
        for character_id in sorted(location.occupants):
            character = self.console.engine.world.get_character(character_id)
            position = marker if character_id == self.console.actor_id and marker is not None else character.position
            color = PALETTE["gold"] if character_id == self.console.actor_id else PALETTE["red"] if character.__class__.__name__ == "Enemy" else "#6593b8"
            self._draw_token(canvas, position, origin_x, origin_y, cell, color, character.name[:1].upper())
        self._draw_doors(canvas, location, grid, origin_x, origin_y)

    def _draw_token(self, canvas, position, origin_x, origin_y, cell, color, label) -> None:
        x, y = origin_x + position[0] * cell + cell / 2, origin_y + position[1] * cell + cell / 2
        radius = max(9, cell * 0.27)
        canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="#f5e9cf", width=2)
        canvas.create_text(x, y, text=label, fill="#17191f", font=("Segoe UI", max(9, int(cell * .24)), "bold"))

    def _draw_doors(self, canvas, location, grid, origin_x, origin_y) -> None:
        doors = self.console.engine.world.world.doors_of(location.id)
        for door in doors:
            cell = door.cell_in(location.id)
            if grid is not None and cell is not None:
                x, y = origin_x + cell[0] * max(28, min(58, (canvas.winfo_width() - 32) // max(grid.width, 1))), origin_y + cell[1] * max(28, min(58, (canvas.winfo_width() - 32) // max(grid.width, 1)))
                canvas.create_rectangle(x + 5, y + 5, x + 16, y + 16, fill="#7ed0bc" if not door.locked else "#bd6257", outline="")
            else:
                canvas.create_text(origin_x, origin_y, anchor="w", text=f"Puerta {door.id} -> {door.other_side(location.id)}",
                                   fill="#7ed0bc" if not door.locked else PALETTE["red"], font=("Segoe UI", 10))

    def _animate_latest_movement(self) -> None:
        if not self.console or not self.console.engine.events.history:
            self._draw_scene()
            return
        event = self.console.engine.events.history[-1]
        if event.type != "CHARACTER_MOVED" or event.actor_id != self.console.actor_id:
            self._draw_scene()
            return
        path = [tuple(cell) for cell in event.data.get("path", [])]
        if not path:
            self._draw_scene()
            return
        self._animate_path(path, 0)

    def _animate_path(self, path, index: int) -> None:
        if index >= len(path):
            self._draw_scene()
            return
        self._draw_scene(marker=path[index])
        self.root.after(90, lambda: self._animate_path(path, index + 1))

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        if hasattr(self, "busy_var"):
            self.busy_var.set(message)
        if hasattr(self, "command_entry"):
            state = "disabled" if busy else "normal"
            self.command_entry.configure(state=state)
            self.send_button.configure(state=state)

    def _finish_waiting(self) -> None:
        self._set_busy(False)
        self.command_entry.focus_set()

    def toggle_ai(self) -> None:
        if self.console is None:
            return
        self.console.narrator = self.ai_enabled_var.get()
        setup = CampaignSetup.from_world(self.console.engine.world.world)
        if setup is not None:
            setup.use_ai_dm = self.console.narrator
            setup.store_in(self.console.engine.world.world)
        self.ai_status_var.set("DM IA: activo" if self.console.narrator else "DM IA: apagado")
        provider = self.wizard.provider
        if self.console.narrator and not provider.is_configured():
            self._append(f"DM IA: falta la clave de {provider.name} ({provider.env_var}). "
                         "Puedes seguir jugando con comandos.")

    def save_game(self) -> None:
        if self.console is None:
            return
        path = filedialog.asksaveasfilename(
            title="Guardar partida", defaultextension=".json",
            filetypes=[("Partidas D&D", "*.json"), ("Todos", "*")],
        )
        if path:
            self.console.handle(f"guardar {Path(path)}")
            self._append_new_console_output()

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def _append_new_console_output(self) -> None:
        value = self.output_buffer.getvalue()
        self._append(value[self.output_position:])
        self.output_position = len(value)

    def _append(self, text: str) -> None:
        if not text:
            return
        stripped = text.lstrip()
        tag = "command" if stripped.startswith("> ") else "notice" if "[!]" in text else "narration"
        self._typing_queue.append((text.rstrip() + "\n", tag))
        if not self._typing:
            self._type_next()

    def _type_next(self) -> None:
        # La animacion va por `after`: si la ventana se ha cerrado o se ha vuelto
        # al asistente mientras tanto, el widget ya no esta y hay que parar.
        if not self._typing_queue or not self.history.winfo_exists():
            self._typing = False
            return
        self._typing = True
        text, tag = self._typing_queue[0]
        self.history.configure(state="normal")
        # Escribe por pequenos grupos para que la animacion siga siendo fluida
        # incluso cuando el DM devuelve una narracion larga.
        chunk = text[:2]
        self.history.insert("end", chunk, tag)
        self.history.configure(state="disabled")
        self.history.see("end")
        remaining = text[len(chunk):]
        if remaining:
            self._typing_queue[0] = (remaining, tag)
            self.root.after(14, self._type_next)
        else:
            self._typing_queue.pop(0)
            self.root.after(80, self._type_next)


def main() -> None:
    root = tk.Tk()
    GameWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
