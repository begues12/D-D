"""Interfaz grafica local y ligera para probar el motor sin terminal."""

from __future__ import annotations

import io
import os
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .campaign import ARCHETYPES, SCENARIOS, CampaignSetup, PlayerSetup, build_campaign
from .console import Console
from .credentials import delete_api_key, load_api_key, save_api_key
from .persistence import load_game, save_game


class GameWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("D&D Engine")
        self.root.geometry("1120x740")
        self.root.minsize(760, 520)
        self._configure_style()
        self.console: Console | None = None
        self.output_buffer = io.StringIO()
        self.output_position = 0
        self._typing_queue: list[tuple[str, str]] = []
        self._typing = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dnd-engine")
        self._busy = False
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._build_start_screen()

    def _configure_style(self) -> None:
        self.colors = {
            "ink": "#f2ead7",
            "muted": "#b6aa94",
            "gold": "#d6a84f",
            "gold_dark": "#8e6425",
            "night": "#17191f",
            "panel": "#22252d",
            "panel_light": "#2b2f39",
            "paper": "#eee3ca",
            "paper_ink": "#2a2520",
            "red": "#bd6257",
        }
        self.root.configure(bg=self.colors["night"])
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("App.TFrame", background=self.colors["night"])
        style.configure("TLabel", background=self.colors["night"], foreground=self.colors["ink"])
        style.configure("TFrame", background=self.colors["night"])
        style.configure("Panel.TFrame", background=self.colors["panel"])
        style.configure("Card.TLabelframe", background=self.colors["panel"], foreground=self.colors["gold"], bordercolor=self.colors["gold_dark"])
        style.configure("Card.TLabelframe.Label", background=self.colors["panel"], foreground=self.colors["gold"], font=("Georgia", 10, "bold"))
        style.configure("Title.TLabel", background=self.colors["night"], foreground=self.colors["gold"], font=("Georgia", 26, "bold"))
        style.configure("Subtitle.TLabel", background=self.colors["night"], foreground=self.colors["muted"], font=("Segoe UI", 10))
        style.configure("Eyebrow.TLabel", background=self.colors["night"], foreground=self.colors["red"], font=("Segoe UI", 9, "bold"))
        style.configure("Panel.TLabel", background=self.colors["panel"], foreground=self.colors["ink"], font=("Segoe UI", 10))
        style.configure("PanelMuted.TLabel", background=self.colors["panel"], foreground=self.colors["muted"], font=("Segoe UI", 9))
        style.configure("Stat.TLabel", background=self.colors["panel_light"], foreground=self.colors["ink"], font=("Segoe UI", 10, "bold"), padding=8)
        style.configure("Gold.TButton", background=self.colors["gold_dark"], foreground=self.colors["ink"], borderwidth=0, padding=(12, 7))
        style.map("Gold.TButton", background=[("active", self.colors["gold"]), ("pressed", self.colors["gold"])])
        style.configure("Tool.TButton", background=self.colors["panel_light"], foreground=self.colors["ink"], borderwidth=0, padding=(9, 6))
        style.map("Tool.TButton", background=[("active", self.colors["gold_dark"]), ("pressed", self.colors["gold_dark"])])
        style.configure("Dark.TCheckbutton", background=self.colors["panel"], foreground=self.colors["ink"], font=("Segoe UI", 9))
        style.map("Dark.TCheckbutton", background=[("active", self.colors["panel"])], foreground=[("active", self.colors["gold"])])
        style.configure("Dark.TEntry", fieldbackground=self.colors["panel_light"], foreground=self.colors["ink"], insertcolor=self.colors["ink"], borderwidth=1)
        style.configure("Dark.TCombobox", fieldbackground=self.colors["panel_light"], background=self.colors["panel_light"], foreground=self.colors["ink"])

    def _build_start_screen(self) -> None:
        self.start_frame = ttk.Frame(self.root, padding=34, style="App.TFrame")
        self.start_frame.pack(fill="both", expand=True)
        ttk.Label(self.start_frame, text="CAMPAIGN BUILDER  /  LOCAL PLAY", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(self.start_frame, text="D&D ENGINE", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self.start_frame,
            text="Prueba el mundo, las reglas y los personajes sin usar el terminal.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(4, 24))

        form = ttk.LabelFrame(self.start_frame, text="Nueva campana", padding=18, style="Card.TLabelframe")
        form.pack(fill="x", anchor="n")
        self.name_var = tk.StringVar(value="Alejandro")
        self.scenario_var = tk.StringVar(value="cripta")
        self.archetype_var = tk.StringVar(value="mago")
        self.api_key_var = tk.StringVar(value=load_api_key() or "")
        self.ai_enabled_var = tk.BooleanVar(value=False)
        self.remember_key_var = tk.BooleanVar(value=True)
        self._field(form, "Nombre del personaje", self.name_var, 0)
        self._field(form, "Escenario", self.scenario_var, 1, list(SCENARIOS))
        self._field(form, "Arquetipo", self.archetype_var, 2, list(ARCHETYPES))
        self._field(form, "Clave API Anthropic", self.api_key_var, 3, secret=True)
        ttk.Checkbutton(
            form, text="Activar DM con IA", variable=self.ai_enabled_var,
            style="Dark.TCheckbutton",
        ).grid(row=4, column=1, sticky="w", pady=(6, 0))
        ttk.Checkbutton(
            form, text="Recordar esta clave en este equipo", variable=self.remember_key_var,
            style="Dark.TCheckbutton",
        ).grid(row=5, column=1, sticky="w", pady=(4, 0))
        ttk.Button(form, text="Empezar partida", command=self.start_game, style="Gold.TButton").grid(
            row=6, column=1, sticky="e", pady=(18, 0)
        )
        ttk.Label(
            self.start_frame,
            text="Tambien puedes abrir una partida JSON guardada.",
        ).pack(anchor="w", pady=(18, 4))
        ttk.Button(self.start_frame, text="Cargar partida", command=self.load_game, style="Tool.TButton").pack(anchor="w")
        ttk.Button(self.start_frame, text="Borrar clave guardada", command=self.clear_saved_key, style="Tool.TButton").pack(anchor="w", pady=(8, 0))

    def _field(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        row: int,
        values: list[str] | None = None,
        secret: bool = False,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 20), pady=5)
        if values:
            widget = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=28, style="Dark.TCombobox")
        else:
            widget = ttk.Entry(parent, textvariable=variable, width=31, style="Dark.TEntry", show="*" if secret else "")
        widget.grid(row=row, column=1, sticky="ew", pady=5)
        parent.columnconfigure(1, weight=1)

    def start_game(self) -> None:
        try:
            setup = CampaignSetup(
                scenario=self.scenario_var.get(),
                players=[PlayerSetup(self.name_var.get(), self.archetype_var.get())],
            )
            engine = build_campaign(setup)
        except ValueError as error:
            messagebox.showerror("No se puede empezar", str(error))
            return
        self._configure_ai()
        self._open_game(engine, setup.players[0].id)

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
        self._configure_ai()
        self.ai_enabled_var.set(bool(setup and setup.use_ai_dm))
        self._open_game(engine, player_id)

    def _configure_ai(self) -> None:
        key = self.api_key_var.get().strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
            if self.remember_key_var.get():
                save_api_key(key)
            else:
                delete_api_key()

    def clear_saved_key(self) -> None:
        delete_api_key()
        self.api_key_var.set("")
        os.environ.pop("ANTHROPIC_API_KEY", None)

    def _open_game(self, engine, player_id: str) -> None:
        self.start_frame.destroy()
        self.output_buffer = io.StringIO()
        self.output_position = 0
        self.console = Console(engine, player_id, stream_out=self.output_buffer)
        self.console.narrator = self.ai_enabled_var.get()
        self._build_game_screen()
        self._set_busy(True, "El DM esta preparando la escena...")
        self._append("El DM esta preparando la escena...")
        future = self._executor.submit(self.console.opening)
        self._poll_future(future, self._finish_opening)

    def _build_game_screen(self) -> None:
        self.game_frame = ttk.Frame(self.root, padding=14, style="App.TFrame")
        self.game_frame.pack(fill="both", expand=True)
        header = ttk.Frame(self.game_frame, style="App.TFrame")
        header.pack(fill="x", pady=(0, 12))
        self.campaign_var = tk.StringVar()
        self.location_var = tk.StringVar()
        ttk.Label(header, textvariable=self.campaign_var, style="Title.TLabel", font=("Georgia", 18, "bold")).pack(side="left")
        ttk.Label(header, text="  /  SALA DE JUEGO", style="Eyebrow.TLabel").pack(side="left", pady=(5, 0))
        toolbar = ttk.Frame(header, style="App.TFrame")
        toolbar.pack(side="right")
        ttk.Button(toolbar, text="Guardar", command=self.save_game, style="Tool.TButton").pack(side="right")
        self.ai_status_var = tk.StringVar(value="DM IA: activo" if self.ai_enabled_var.get() else "DM IA: apagado")
        ttk.Checkbutton(
            toolbar, textvariable=self.ai_status_var, variable=self.ai_enabled_var,
            command=self.toggle_ai, style="Dark.TCheckbutton",
        ).pack(side="right", padx=(0, 12))

        content = ttk.Frame(self.game_frame, style="App.TFrame")
        content.pack(fill="both", expand=True)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(content, width=220, padding=(0, 0, 14, 0), style="App.TFrame")
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        character_panel = ttk.LabelFrame(sidebar, text="Tu personaje", padding=12, style="Card.TLabelframe")
        character_panel.pack(fill="x", pady=(0, 10))
        self.character_var = tk.StringVar()
        self.hp_var = tk.StringVar()
        ttk.Label(character_panel, textvariable=self.character_var, style="Panel.TLabel", font=("Georgia", 13, "bold")).pack(anchor="w")
        ttk.Label(character_panel, textvariable=self.hp_var, style="Stat.TLabel").pack(fill="x", pady=(10, 6))
        ttk.Label(character_panel, textvariable=self.location_var, style="PanelMuted.TLabel", wraplength=180).pack(anchor="w")
        tools = ttk.LabelFrame(sidebar, text="Acciones", padding=10, style="Card.TLabelframe")
        tools.pack(fill="x")
        for label, command in (
            ("Mirar", "mirar"), ("Mapa", "mapa"), ("Estado", "estado"),
            ("Inventario", "inventario"), ("Ayuda", "ayuda"), ("Pasar turno", "turno"),
        ):
            ttk.Button(tools, text=label, command=lambda value=command: self.submit(value), style="Tool.TButton").pack(
                fill="x", pady=2
            )

        play_area = ttk.Frame(content, style="Panel.TFrame", padding=8)
        play_area.grid(row=0, column=1, sticky="nsew")
        play_area.columnconfigure(0, weight=1)
        play_area.rowconfigure(1, weight=1)
        self.scene_title_var = tk.StringVar()
        ttk.Label(play_area, textvariable=self.scene_title_var, style="Panel.TLabel",
                  font=("Georgia", 12, "bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(2, 8))
        self.scene_canvas = tk.Canvas(
            play_area, height=300, bg="#171a20", highlightthickness=1,
            highlightbackground=self.colors["gold_dark"], relief="flat",
        )
        self.scene_canvas.grid(row=1, column=0, sticky="ew", padx=2)
        self.scene_canvas.bind("<Configure>", lambda _event: self._draw_scene())

        history_frame = ttk.Frame(play_area, style="Panel.TFrame", padding=(3, 10, 3, 3))
        history_frame.grid(row=2, column=0, sticky="nsew")
        history_frame.rowconfigure(0, weight=1)
        history_frame.columnconfigure(0, weight=1)
        self.history = tk.Text(history_frame, wrap="word", state="disabled", padx=18, pady=16,
                               bg=self.colors["paper"], fg=self.colors["paper_ink"],
                               insertbackground=self.colors["paper_ink"], relief="flat",
                               font=("Segoe UI", 10), spacing1=2, spacing3=5)
        self.history.tag_configure("narration", foreground=self.colors["paper_ink"])
        self.history.tag_configure("command", foreground=self.colors["gold_dark"], font=("Segoe UI", 10, "bold"))
        self.history.tag_configure("notice", foreground=self.colors["red"], font=("Segoe UI", 10, "bold"))
        self.history.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(history_frame, orient="vertical", command=self.history.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
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
        self.campaign_var.set(setup.campaign_title if setup else self.console.engine.world.world.name)
        self.character_var.set(f"{actor.name}  ·  nivel {actor.level}")
        self.hp_var.set(f"HP  {actor.hp} / {actor.max_hp}")
        self.location_var.set(location.name if location else "Ubicacion desconocida")

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

    def _finish_command(self, _result) -> None:
        self._append_new_console_output()
        self._refresh_panel()
        self._animate_latest_movement()
        self._finish_waiting()

    def _draw_scene(self, marker=None) -> None:
        if not hasattr(self, "scene_canvas") or self.console is None:
            return
        canvas = self.scene_canvas
        canvas.delete("all")
        location = self.console.engine.world.location_of(self.console.actor_id)
        self.scene_title_var.set(f"{location.name.upper()}  /  {location.id}")
        grid = location.grid
        if grid is None:
            canvas.create_text(20, 35, anchor="w", text="Teatro de la mente", fill=self.colors["gold"],
                               font=("Georgia", 15, "bold"))
            canvas.create_text(20, 68, anchor="w", text=location.description or "La sala no tiene cuadricula.",
                               fill=self.colors["ink"], font=("Segoe UI", 10))
            self._draw_doors(canvas, location, None, 20, 115)
            return
        cell = max(28, min(58, (canvas.winfo_width() - 32) // max(grid.width, 1)))
        origin_x, origin_y = 16, 16
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
            color = self.colors["gold"] if character_id == self.console.actor_id else self.colors["red"] if character.__class__.__name__ == "Enemy" else "#6593b8"
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
                                   fill="#7ed0bc" if not door.locked else self.colors["red"], font=("Segoe UI", 10))

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
        if self.console.narrator and not self.api_key_var.get().strip() and "ANTHROPIC_API_KEY" not in os.environ:
            self._append("DM IA: falta ANTHROPIC_API_KEY. Puedes seguir jugando con comandos.")

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
        if not self._typing_queue:
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
