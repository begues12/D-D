"""Menu hablado: el DM va proponiendo y preguntando hasta montar la campana.

No es una pantalla de opciones, es una conversacion guiada. Todo lo que dice
sale por `say()` y todo lo que oye entra por `ask()`, asi que ponerle voz mas
adelante es sustituir esos dos metodos, no reescribir el flujo.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, TextIO

from .campaign import (
    ARCHETYPES,
    DIFFICULTIES,
    MAX_PLAYERS,
    SCENARIOS,
    TONES,
    CampaignSetup,
    PlayerSetup,
    build_campaign,
)
from .game import GameEngine
from .persistence import load_game


class Cancelled(Exception):
    """El jugador ha querido salir a mitad de la conversacion."""


class SetupMenu:
    def __init__(self, stream_in: TextIO | None = None, stream_out: TextIO | None = None) -> None:
        self.stream_in = stream_in or sys.stdin
        self.stream_out = stream_out or sys.stdout

    # -- voz y oido --------------------------------------------------------

    def say(self, text: str = "") -> None:
        self.stream_out.write(text + "\n")

    def ask(self, question: str, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        while True:
            self.stream_out.write(f"{question}{suffix}\n> ")
            self.stream_out.flush()
            line = self.stream_in.readline()
            if not line:
                raise Cancelled
            answer = line.strip()
            if answer.lower() in ("salir", "quit", "exit"):
                raise Cancelled
            if answer:
                return answer
            if default is not None:
                return default
            self.say("Necesito una respuesta.")

    def ask_number(self, question: str, low: int, high: int, default: int) -> int:
        while True:
            answer = self.ask(question, str(default))
            try:
                number = int(answer)
            except ValueError:
                self.say(f"Dime un numero entre {low} y {high}.")
                continue
            if low <= number <= high:
                return number
            self.say(f"Tiene que estar entre {low} y {high}.")

    def ask_yes_no(self, question: str, default: bool) -> bool:
        answer = self.ask(question, "si" if default else "no").lower()
        return answer.startswith(("s", "y", "1"))

    def choose(self, question: str, options: list[tuple[str, str, str]], default: str) -> str:
        """Propone opciones numeradas con su descripcion y devuelve el id elegido."""
        identifiers = [one[0] for one in options]
        for number, (identifier, name, description) in enumerate(options, start=1):
            mark = " (por defecto)" if identifier == default else ""
            self.say(f"  {number}. {name}{mark}")
            self.say(f"     {description}")
        default_number = identifiers.index(default) + 1 if default in identifiers else 1
        while True:
            answer = self.ask(question, str(default_number))
            if answer.lower() in identifiers:
                return answer.lower()
            try:
                number = int(answer)
            except ValueError:
                self.say("No he entendido cual. Dime el numero.")
                continue
            if 1 <= number <= len(identifiers):
                return identifiers[number - 1]
            self.say(f"Solo hay {len(identifiers)} opciones.")

    # -- menu principal ----------------------------------------------------

    def run(self) -> tuple[GameEngine, str] | None:
        """Devuelve (motor, id del primer jugador) o None si se sale."""
        self.say("=" * 60)
        self.say("  MOTOR DE D&D")
        self.say("=" * 60)
        while True:
            self.say()
            self.say("  1. Montar una campana nueva")
            self.say("  2. Retomar una partida guardada")
            self.say("  3. Salir")
            try:
                choice = self.ask("Que hacemos?", "1")
            except Cancelled:
                return None
            if choice.startswith("3") or choice.lower().startswith("sal"):
                self.say("Hasta la proxima.")
                return None
            try:
                if choice.startswith("2") or choice.lower().startswith(("ret", "car")):
                    loaded = self.load_campaign()
                    if loaded is not None:
                        return loaded
                    continue
                return self.new_campaign()
            except Cancelled:
                self.say("Dejamos la preparacion. Volvemos al principio.")

    def load_campaign(self) -> tuple[GameEngine, str] | None:
        path = self.ask("De que fichero la retomo?", "partida.json")
        try:
            engine = load_game(path)
        except (OSError, ValueError, KeyError) as error:
            self.say(f"No he podido cargarla: {error}")
            return None
        setup = CampaignSetup.from_world(engine.world.world)
        first = setup.players[0].id if setup else next(iter(engine.world.world.characters))
        self.say(f"Retomamos '{engine.world.world.name}'.")
        if setup:
            self.say(setup.summary())
        return engine, first

    # -- conversacion de preparacion ---------------------------------------

    def new_campaign(self) -> tuple[GameEngine, str]:
        setup = CampaignSetup()
        self.say()
        self.say("Muy bien. Antes de empezar necesito saber que historia quereis jugar.")
        self.say("Responde con el numero, o escribe 'salir' para dejarlo.")

        setup.scenario = self.ask_scenario()
        setup.players = self.ask_party()
        setup.tone = self.ask_tone()
        setup.difficulty = self.ask_difficulty()
        setup.premise = self.ask_premise()
        setup.use_ai_dm = self.ask_ai_dm()
        setup.title = self.ask_title(setup)

        while True:
            self.say()
            self.say("Esto es lo que vamos a jugar:")
            self.say(setup.summary())
            if self.ask_yes_no("Lo damos por bueno?", True):
                break
            self.say("Dime que quieres cambiar.")
            self.amend(setup)

        engine = build_campaign(setup)
        self.say()
        self.say(f"Empieza '{setup.campaign_title}'.")
        return engine, setup.players[0].id

    def ask_scenario(self) -> str:
        self.say()
        self.say("Estas son las historias que tengo preparadas:")
        return self.choose(
            "Cual montamos?",
            [(one, data["name"], data["description"]) for one, data in SCENARIOS.items()],
            "taberna",
        )

    def ask_party(self) -> list[PlayerSetup]:
        self.say()
        count = self.ask_number("Cuantos sois?", 1, MAX_PLAYERS, 1)
        players: list[PlayerSetup] = []
        taken: set[str] = set()
        for number in range(1, count + 1):
            self.say()
            who = "Tu personaje" if count == 1 else f"Jugador {number}"
            name = self.ask_unique_name(f"{who}: como se llama?", taken, number)
            taken.add(name.strip().lower())
            self.say(f"Y que sabe hacer {name}?")
            archetype = self.choose(
                "Que es?",
                [(one, arch.name, arch.description) for one, arch in ARCHETYPES.items()],
                "guerrero",
            )
            players.append(PlayerSetup(name, archetype))
        return players

    def ask_unique_name(self, question: str, taken: set[str], number: int) -> str:
        while True:
            name = self.ask(question, f"Heroe {number}")
            if name.strip().lower() not in taken:
                return name
            self.say("Ya hay alguien con ese nombre en el grupo.")

    def ask_tone(self) -> str:
        self.say()
        self.say("Y con que tono quereis que lo narre?")
        return self.choose(
            "Que tono?",
            [(one, tone.name, tone.description) for one, tone in TONES.items()],
            "heroico",
        )

    def ask_difficulty(self) -> str:
        self.say()
        self.say("Cuanto quereis que aprieten los enemigos?")
        return self.choose(
            "Que dificultad?",
            [(one, level.name, level.description) for one, level in DIFFICULTIES.items()],
            "normal",
        )

    def ask_premise(self) -> str:
        self.say()
        self.say("Hay algo que quieras que tenga en cuenta? Un motivo para estar ahi, "
                 "una deuda, alguien a quien buscais...")
        answer = self.ask("Cuentamelo, o dale a intro para dejarlo asi.", "-")
        return "" if answer.strip() in ("-", "") else answer.strip()

    def ask_ai_dm(self) -> bool:
        self.say()
        self.say("Puedo narrar con un DM de IA, que interpreta lo que escribis en "
                 "lenguaje natural. Necesita ANTHROPIC_API_KEY; sin ella se juega "
                 "igual con los comandos de siempre.")
        return self.ask_yes_no("Activo el DM con IA?", False)

    def ask_title(self, setup: CampaignSetup) -> str:
        self.say()
        default = SCENARIOS[setup.scenario]["name"]
        answer = self.ask("Como quereis llamar a la campana?", default)
        return "" if answer == default else answer

    def amend(self, setup: CampaignSetup) -> None:
        field = self.choose(
            "Que cambio?",
            [
                ("escenario", "El escenario", "Otra historia distinta."),
                ("grupo", "El grupo", "Numero de jugadores, nombres y arquetipos."),
                ("tono", "El tono", "Como se narra."),
                ("dificultad", "La dificultad", "Cuanto aprietan los enemigos."),
                ("premisa", "La premisa", "Lo que le pedis al DM."),
                ("ia", "El DM con IA", "Activarlo o desactivarlo."),
                ("titulo", "El titulo", "El nombre de la campana."),
            ],
            "grupo",
        )
        actions: dict[str, Callable[[], Any]] = {
            "escenario": lambda: setattr(setup, "scenario", self.ask_scenario()),
            "grupo": lambda: setattr(setup, "players", self.ask_party()),
            "tono": lambda: setattr(setup, "tone", self.ask_tone()),
            "dificultad": lambda: setattr(setup, "difficulty", self.ask_difficulty()),
            "premisa": lambda: setattr(setup, "premise", self.ask_premise()),
            "ia": lambda: setattr(setup, "use_ai_dm", self.ask_ai_dm()),
            "titulo": lambda: setattr(setup, "title", self.ask_title(setup)),
        }
        actions[field]()
