"""CLI interactiva para jugar sin IA.

La consola solo traduce texto a `Intent` y presenta lo que devuelve el motor.
No decide nada: si un ataque acierta o una puerta se abre lo dicen las reglas.
Esa misma frontera la ocupara despues el DM basado en IA.
"""

from __future__ import annotations

import sys
from typing import Any, Callable, TextIO

from .actions import ActionResult, Intent, execute
from .events import Event
from .game import GameEngine
from .dice import Dice
from .models import Character, Consumable, Enemy, ItemEffect, Weapon
from .persistence import load_game, save_game
from . import tactics


class Console:
    def __init__(
        self,
        engine: GameEngine,
        player_id: str,
        stream_in: TextIO | None = None,
        stream_out: TextIO | None = None,
    ) -> None:
        self.engine = engine
        self.player_id = player_id
        self.actor_id = player_id
        self.auto_enemies = True
        self.narrator = False
        self._dungeon_master = None
        self.stream_in = stream_in or sys.stdin
        self.stream_out = stream_out or sys.stdout
        self.commands = self._build_commands()

    # -- bucle -----------------------------------------------------------

    def run(self) -> None:
        self.say(self.opening())
        while True:
            self.stream_out.write(f"\n{self._prompt()} ")
            self.stream_out.flush()
            line = self.stream_in.readline()
            if not line:
                self.say("\nHasta la proxima.")
                return
            if not self.handle(line.strip()):
                return

    def opening(self) -> str:
        """Apertura de la aventura. Con el DM activo, la narra el modelo."""
        from .campaign import briefing

        intro = None
        if self.narrator:
            from .ai_dm import DungeonMasterError

            try:
                intro = self.dungeon_master().open_scene(self.engine, self.actor_id)
                self.engine.memory.remember_narration(intro)
            except DungeonMasterError as error:
                # Sin narracion se abre con el gancho escrito del escenario.
                intro = None
                self.say(f"[!] El DM no ha podido abrir la escena: {error}")
        return (briefing(self.engine, self.actor_id, intro)
                + "\n\nEscribe 'ayuda' para los comandos, 'intro' para releer esto, "
                  "'salir' para terminar.")

    def handle(self, line: str) -> bool:
        """Ejecuta una linea. Devuelve False cuando hay que salir."""
        if not line or line.startswith("#"):
            return True
        verb, *arguments = line.split()
        command = self.commands.get(verb.lower())
        if command is None:
            if self.narrator:
                return self.handle_natural_language(line)
            self.say(f"[!] No conozco '{verb}'. Prueba con 'ayuda'. "
                     f"Con 'narrador' activo, el DM interpreta el texto libre.")
            return True
        seen = len(self.engine.events.history)
        try:
            keep_going = command(arguments) is not False
        except ValueError as error:
            self.say(f"[!] {error}")
            return True
        except IndexError:
            self.say(f"[!] Faltan argumentos para '{verb}'. Mira 'ayuda'.")
            return True
        self._report_events(seen)
        return keep_going

    def say(self, text: str = "") -> None:
        self.stream_out.write(text + "\n")

    def _prompt(self) -> str:
        actor = self.engine.world.get_character(self.actor_id)
        return (f"[{actor.name} {actor.hp}/{actor.max_hp} hp "
                f"{actor.resources.movement} pies] >")

    def _name(self, character_id: str | None) -> str:
        if character_id is None:
            return "alguien"
        try:
            return self.engine.world.get_character(character_id).name
        except ValueError:
            return character_id

    # -- consecuencias ----------------------------------------------------

    def _report_events(self, seen: int) -> None:
        """Narra las consecuencias que el resumen de la accion no cuenta."""
        for event in self.engine.events.history[seen:]:
            line = self._describe(event)
            if line:
                self.say("  " + line)

    def _describe(self, event: Event) -> str | None:
        target, actor = self._name(event.target_id), self._name(event.actor_id)
        data = event.data
        if event.type == "NPC_DIES":
            return f"{target} cae derrotado."
        if event.type == "CHARACTER_DOWNED":
            return f"{target} cae inconsciente y empieza a agonizar."
        if event.type == "DEATH_SAVE":
            if data.get("dead"):
                return f"{actor} falla su tercera salvacion contra muerte."
            if data.get("revived"):
                return f"{actor} saca un 20 natural y vuelve en si."
            if data.get("stabilized"):
                return f"{actor} se estabiliza."
            return (f"{actor} tira salvacion contra muerte ({data.get('natural_roll')}): "
                    f"{data.get('successes')} exitos, {data.get('failures')} fallos.")
        if event.type == "CHARACTER_REVIVED":
            return f"{actor} se recupera con {data.get('hp')} HP."
        if event.type == "CONDITION_EXPIRED":
            return f"a {actor} se le pasa el estado '{data.get('condition')}'."
        if event.type == "XP_AWARDED":
            return f"{actor} gana {data.get('amount')} de experiencia."
        if event.type == "LEVEL_UP":
            return f"{actor} sube al nivel {data.get('level')}."
        if event.type == "QUEST_OBJECTIVE_COMPLETED":
            return f"objetivo cumplido: {data.get('objective_id')}."
        if event.type == "QUEST_COMPLETED":
            return f"mision completada: {data.get('quest_id')}."
        if event.type == "QUEST_FAILED":
            return f"mision fracasada: {data.get('quest_id')}."
        if event.type == "TURN_SKIPPED":
            return f"{actor} no puede actuar y pierde el turno."
        return None

    # -- despacho de intenciones -----------------------------------------

    def _run_intent(self, action: str, **parameters: Any) -> ActionResult:
        actor = self.engine.world.get_character(self.actor_id)
        result = execute(self.engine, Intent(action, parameters, self.actor_id))
        self.say(f"{actor.name} {result.summary}")
        return result

    def _build_commands(self) -> dict[str, Callable[[list[str]], Any]]:
        table = {
            ("ayuda", "help", "?"): self.help,
            ("mirar", "look"): self.look,
            ("intro", "resumen"): self.show_briefing,
            ("mapa", "map"): self.show_map,
            ("estado", "status"): self.status,
            ("inventario", "inv"): self.inventory,
            ("mover", "move"): self.move,
            ("acercarse", "approach"): self.approach,
            ("atacar", "attack"): self.attack,
            ("lanzar", "cast"): self.cast,
            ("puerta", "door"): self.use_door,
            ("abrir", "unlock"): self.unlock_door,
            ("coger", "take"): self.take_item,
            ("usar", "use"): self.use_item,
            ("soltar", "drop"): self.drop_item,
            ("ir", "go"): self.travel,
            ("combate", "fight"): self.begin_encounter,
            ("turno", "pasar", "next"): self.end_turn,
            ("fincombate", "endfight"): self.end_encounter,
            ("curar", "heal"): self.heal,
            ("salvacion", "save"): self.saving_throw,
            ("tirar", "dados", "roll"): self.roll_dice,
            ("misiones", "quests"): self.quests,
            ("eventos", "log"): self.events,
            ("memoria", "memory"): self.show_memory,
            ("controlar", "control"): self.control,
            ("auto",): self.toggle_auto,
            ("dm", "di"): self.ask_dungeon_master,
            ("narrador", "narrator"): self.toggle_narrator,
            ("guardar", "savegame"): self.save,
            ("cargar", "loadgame"): self.load,
            ("salir", "quit", "exit"): self.quit,
        }
        return {alias: handler for aliases, handler in table.items() for alias in aliases}

    # -- comandos de informacion -----------------------------------------

    def help(self, _arguments: list[str]) -> None:
        self.say("Comandos:")
        for text in (
            "intro                     donde estais, quienes sois y que os jugais",
            "mirar                     describe la ubicacion",
            "mapa                      dibuja la cuadricula",
            "estado [id]               hp, condiciones y recursos",
            "inventario [id]           objetos y hechizos",
            "mover X Y                 moverse a una casilla",
            "acercarse OBJETIVO        llegar a una casilla libre junto a alguien",
            "atacar OBJETIVO [ARMA]    atacar con un arma",
            "lanzar HECHIZO OBJETIVO   lanzar un hechizo",
            "abrir PUERTA              abrir con la llave del inventario",
            "coger OBJETO              recoger algo del suelo",
            "usar OBJETO [OBJETIVO]    beber o administrar un consumible",
            "soltar OBJETO             dejar algo en el suelo",
            "puerta PUERTA             cruzar una puerta contigua",
            "ir UBICACION              ir a una ubicacion conectada",
            "combate [ids...]          iniciar encuentro (por defecto, los presentes)",
            "turno                     terminar el turno y pasar al siguiente",
            "fincombate                terminar el encuentro",
            "curar OBJETIVO N          curar puntos de golpe",
            "salvacion HABILIDAD CD    tirar una salvacion",
            "tirar 2d6+3               una tirada de dados suelta",
            "misiones                  estado de las misiones",
            "eventos [n]               ultimos eventos del bus",
            "memoria                   hechos y cronica de la campana",
            "controlar ID              cambiar de personaje",
            "auto                      alternar turnos automaticos de enemigos",
            "dm TEXTO                  hablar en lenguaje natural con el DM (IA)",
            "narrador                  mandar al DM todo lo que no sea un comando",
            "guardar FICHERO           guardar la campana",
            "cargar FICHERO            cargar una campana",
            "salir                     terminar",
        ):
            self.say("  " + text)

    def show_briefing(self, _arguments: list[str]) -> None:
        from .campaign import briefing

        self.say(briefing(self.engine, self.actor_id))

    def look(self, _arguments: list[str]) -> None:
        location = self.engine.world.location_of(self.actor_id)
        self.say(f"\n== {location.name} ==")
        if location.description:
            self.say(location.description)
        for occupant_id in sorted(location.occupants):
            if occupant_id == self.actor_id:
                continue
            other = self.engine.world.get_character(occupant_id)
            distance = self.engine.distance_between(self.actor_id, occupant_id)
            marker = "" if distance is None else f", a {distance} pies"
            self.say(f"  - {other.name} ({occupant_id}): {self._condition_of(other)}{marker}")
        for item in location.items:
            where = f", en {item.cell}" if item.cell else ""
            self.say(f"  . en el suelo: {item.name} [{item.id}]{where}")
        for door in self.engine.world.world.doors_of(location.id):
            if door.hidden:
                continue
            state = "cerrada con llave" if door.locked else "abierta"
            self.say(f"  > puerta '{door.id}' hacia {door.other_side(location.id)} ({state})")

    def show_map(self, _arguments: list[str]) -> None:
        location = self.engine.world.location_of(self.actor_id)
        if location.grid is None:
            self.say(f"{location.name} no tiene cuadricula.")
            return
        grid = location.grid
        occupants = {
            self.engine.world.get_character(occupant_id).position: occupant_id
            for occupant_id in sorted(location.occupants)
        }
        doors = {door.cell_in(location.id): door
                 for door in self.engine.world.world.doors_of(location.id)
                 if door.cell_in(location.id) is not None}
        loot = {item.cell for item in location.items if item.cell is not None}
        self.say("    " + " ".join(str(x) for x in range(grid.width)))
        for y in range(grid.height):
            row = []
            for x in range(grid.width):
                cell = (x, y)
                if cell in occupants:
                    # La inicial del nombre, no la del id: dos "hero-..." darian
                    # la misma letra para todo el grupo.
                    row.append("@" if occupants[cell] == self.actor_id
                               else self._name(occupants[cell])[0].upper())
                elif cell in grid.blocked:
                    row.append("#")
                elif cell in doors:
                    row.append("+")
                elif cell in loot:
                    row.append("*")
                else:
                    row.append(".")
            self.say(f"  {y} " + " ".join(row))
        self.say("  @ tu, # obstaculo, + puerta, * objeto")

    def status(self, arguments: list[str]) -> None:
        character = self.engine.world.get_character(arguments[0] if arguments else self.actor_id)
        self.say(f"{character.name} ({character.id}) nivel {character.level}")
        self.say(f"  HP {character.hp}/{character.max_hp}  CA {character.armor_class}  "
                 f"XP {character.experience}")
        self.say(f"  estado: {self._condition_of(character)}  posicion {character.position}")
        resources = character.resources
        self.say(f"  accion {'si' if resources.action else 'no'}, "
                 f"adicional {'si' if resources.bonus_action else 'no'}, "
                 f"reaccion {'si' if resources.reaction else 'no'}, "
                 f"movimiento {resources.movement} pies")
        if character.is_dying:
            saves = character.death_saves
            self.say(f"  salvaciones contra muerte: {saves.successes} exitos, "
                     f"{saves.failures} fallos")

    def inventory(self, arguments: list[str]) -> None:
        character = self.engine.world.get_character(arguments[0] if arguments else self.actor_id)
        for item in character.inventory:
            if isinstance(item, Weapon):
                extra = f" ({item.damage}, alcance {item.reach})"
            elif isinstance(item, Consumable):
                healing = f" {item.healing}" if item.effect is ItemEffect.HEAL else ""
                extra = f" ({item.effect.value}{healing}, {item.uses} usos)"
            else:
                extra = ""
            self.say(f"  - {item.name} [{item.id}]{extra}")
        for spell in character.spells:
            slots = character.spell_slots.get(spell.level, 0)
            self.say(f"  * {spell.name} [{spell.id}] nivel {spell.level}, "
                     f"{slots} espacios, alcance {spell.range_feet}")
        if not character.inventory and not character.spells:
            self.say("  (nada)")

    def quests(self, _arguments: list[str]) -> None:
        if not self.engine.quests.quests:
            self.say("  (sin misiones)")
        for quest in self.engine.quests.quests.values():
            self.say(f"  {quest.name} [{quest.id}]: {quest.status}")
            for objective in quest.objectives.values():
                mark = "x" if objective.completed else " "
                self.say(f"    [{mark}] {objective.description}")

    def events(self, arguments: list[str]) -> None:
        count = int(arguments[0]) if arguments else 10
        for event in self.engine.events.history[-count:]:
            actor = event.actor_id or "-"
            target = f" -> {event.target_id}" if event.target_id else ""
            self.say(f"  {event.type} ({actor}{target}) {event.data}")

    def show_memory(self, _arguments: list[str]) -> None:
        self.say(self.engine.memory.recall())

    # -- comandos de accion ----------------------------------------------

    def move(self, arguments: list[str]) -> None:
        self._run_intent("move", x=arguments[0], y=arguments[1])

    def approach(self, arguments: list[str]) -> None:
        self._run_intent("approach", target=arguments[0])

    def attack(self, arguments: list[str]) -> None:
        self._run_intent("attack", target=arguments[0],
                         weapon=arguments[1] if len(arguments) > 1 else None)

    def cast(self, arguments: list[str]) -> None:
        self._run_intent("cast", spell=arguments[0], target=arguments[1])

    def use_door(self, arguments: list[str]) -> None:
        self._run_intent("use_door", door=arguments[0])
        self.look([])

    def unlock_door(self, arguments: list[str]) -> None:
        self._run_intent("unlock_door", door=arguments[0])

    def take_item(self, arguments: list[str]) -> None:
        self._run_intent("take", item=arguments[0])

    def use_item(self, arguments: list[str]) -> None:
        self._run_intent("use", item=arguments[0],
                         target=arguments[1] if len(arguments) > 1 else None)

    def drop_item(self, arguments: list[str]) -> None:
        self._run_intent("drop", item=arguments[0])

    def travel(self, arguments: list[str]) -> None:
        self._run_intent("travel", location=arguments[0])
        self.look([])

    def heal(self, arguments: list[str]) -> None:
        self._run_intent("heal", target=arguments[0], amount=arguments[1])

    def saving_throw(self, arguments: list[str]) -> None:
        self._run_intent("saving_throw", ability=arguments[0], dc=arguments[1])

    def roll_dice(self, arguments: list[str]) -> None:
        """Una tirada suelta, con el mismo lanzador que usa el motor."""
        if not arguments:
            raise ValueError("Escribe una tirada, por ejemplo: tirar 2d6+3")
        dice = Dice.parse("".join(arguments))
        self.say(f"  {dice.roll(self.engine.combat.roller).detail}")

    # -- combate ----------------------------------------------------------

    def begin_encounter(self, arguments: list[str]) -> None:
        if arguments:
            participants = arguments
        else:
            location = self.engine.world.location_of(self.actor_id)
            participants = sorted(
                occupant for occupant in location.occupants
                if self.engine.world.get_character(occupant).is_alive
            )
        order = self.engine.begin_encounter(participants)
        names = ", ".join(self._name(one) for one in order)
        self.say(f"Comienza el combate. Orden de iniciativa: {names}.")
        self.engine.next_turn()
        self._resume_turn()

    def end_turn(self, _arguments: list[str]) -> None:
        if self.engine.encounter is None:
            self.engine.start_turn(self.actor_id)
            self.say("No hay combate; empiezas un turno nuevo.")
            return
        self.engine.next_turn()
        self._resume_turn()

    def end_encounter(self, _arguments: list[str]) -> None:
        self.engine.end_encounter()
        if self.actor_id not in self.party:
            self.actor_id = self.player_id
        self.say("Termina el combate.")

    def _resume_turn(self) -> None:
        """Anuncia el turno en curso y juega solo los de los enemigos.

        El personaje controlado solo cambia cuando el turno es de alguien que
        lleva el jugador: durante un turno automatico solo se mira.
        """
        while True:
            encounter = self.engine.encounter
            if encounter is None or encounter.order is None:
                return
            character = self.engine.world.get_character(encounter.order[encounter.current_index])
            self.say(f"\n-- turno de {character.name} (ronda {encounter.round_number}) --")
            if not self._should_autoplay(character):
                self.actor_id = character.id
                if not self._someone_left_to_fight():
                    self.say("Ya no quedan dos bandos en pie. "
                             "Escribe 'fincombate' para cerrarlo.")
                return
            results = tactics.take_turn(self.engine, character.id)
            for result in results:
                self.say(f"{character.name} {result.summary}")
            if not results:
                self.say(f"{character.name} no hace nada.")
            if not self._someone_left_to_fight():
                if self.actor_id not in self.party:
                    self.actor_id = self.player_id
                self.say("Ya no quedan dos bandos en pie. Escribe 'fincombate' para cerrarlo.")
                return
            self.engine.next_turn()

    def _should_autoplay(self, character: Character) -> bool:
        return (self.auto_enemies and character.id not in self.party
                and isinstance(character, Enemy) and character.is_conscious)

    def _someone_left_to_fight(self) -> bool:
        encounter = self.engine.encounter
        if encounter is None or encounter.order is None:
            return False
        participants = [self.engine.world.get_character(one) for one in encounter.order]
        return any(
            tactics.is_hostile(one, other) and one.is_conscious and other.is_conscious
            for one in participants for other in participants
        )

    # -- DM con IA ---------------------------------------------------------

    def ask_dungeon_master(self, arguments: list[str]) -> None:
        if not arguments:
            raise IndexError
        self.handle_natural_language(" ".join(arguments))

    def handle_natural_language(self, message: str) -> bool:
        """Manda el texto al DM. Los fallos del modelo no tumban la partida."""
        from .ai_dm import NO_ACTION, DungeonMasterError

        try:
            turn = self.dungeon_master().play(self.engine, self.actor_id, message)
        except DungeonMasterError as error:
            self.say(f"[!] DM no disponible: {error}")
            if error.retryable:
                self.say("    Tu turno sigue intacto: repite la frase.")
            return True
        self.say("")
        self.say(turn.narration)
        detail = " + ".join(
            f"sin accion: {one.parameters.get('reason', '')}"
            if one.action == NO_ACTION else f"{one.action} {one.parameters}"
            for one in turn.intents)
        if turn.error:
            detail += f" -> rechazada: {turn.error}"
        self.say(f"  ({detail})")
        return True

    def dungeon_master(self):
        if self._dungeon_master is None:
            from .ai_dm import DungeonMaster
            from .campaign import CampaignSetup, story_brief

            setup = CampaignSetup.from_world(self.engine.world.world)
            self._dungeon_master = DungeonMaster(
                story=story_brief(setup) if setup else "",
                provider=setup.ai_provider or None if setup else None,
                model=setup.ai_model or None if setup else None)
        return self._dungeon_master

    @property
    def party(self) -> list[str]:
        """Ids de los personajes que lleva el jugador."""
        from .campaign import CampaignSetup

        setup = CampaignSetup.from_world(self.engine.world.world)
        if setup is None:
            return [self.player_id]
        return [one.id for one in setup.players
                if one.id in self.engine.world.world.characters]

    def toggle_narrator(self, _arguments: list[str]) -> None:
        self.narrator = not self.narrator
        estado = "si" if self.narrator else "no"
        self.say(f"El DM interpreta el texto libre: {estado}.")

    def toggle_auto(self, _arguments: list[str]) -> None:
        self.auto_enemies = not self.auto_enemies
        self.say(f"Turnos automaticos de enemigos: {'si' if self.auto_enemies else 'no'}.")

    def control(self, arguments: list[str]) -> None:
        character = self.engine.world.get_character(arguments[0])
        self.actor_id = character.id
        self.say(f"Ahora llevas a {character.name}.")

    # -- persistencia -----------------------------------------------------

    def save(self, arguments: list[str]) -> None:
        save_game(self.engine, arguments[0])
        self.say(f"Campana guardada en {arguments[0]}.")

    def load(self, arguments: list[str]) -> None:
        self.engine = load_game(arguments[0])
        self.actor_id = self.player_id
        self.say(f"Campana cargada de {arguments[0]}.")
        self.look([])

    def quit(self, _arguments: list[str]) -> bool:
        self.say("Hasta la proxima.")
        return False

    @staticmethod
    def _condition_of(character: Character) -> str:
        if character.is_dead:
            return "muerto"
        if character.is_dying:
            return "agonizando"
        if not character.is_conscious:
            return "inconsciente"
        if character.conditions:
            return ", ".join(sorted(condition.value for condition in character.conditions))
        return "en pie"


def main() -> None:
    from .menu import SetupMenu

    started = SetupMenu().run()
    if started is None:
        return
    engine, player_id = started
    console = Console(engine, player_id)
    from .campaign import CampaignSetup

    setup = CampaignSetup.from_world(engine.world.world)
    console.narrator = bool(setup and setup.use_ai_dm)
    console.run()
