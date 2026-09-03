"""DM basado en IA: interpreta lenguaje natural y narra lo que decide el motor.

El ciclo tiene dos llamadas al modelo y el motor en medio:

    texto del jugador -> interpretar -> Intent -> MOTOR -> resultado -> narrar

El modelo nunca decide si un ataque acierta ni cuanto dano hace. Las dos llamadas
reciben la memoria de campana, que es lo que da continuidad entre turnos.

En la primera llamada solo elige acciones del catalogo de `actions.py`, con
`tool_choice` forzado: la respuesta es siempre una o varias intenciones
estructuradas. Se admite mas de una porque los jugadores hablan en secuencias
("me acerco y le clavo la espada"), y la economia de turno lo permite. Se
ejecutan en orden y se paran en el primer rechazo de las reglas.

En la segunda llamada recibe los resultados reales y los eventos, y solo pone las
palabras. Si esa llamada falla, el turno ya esta ejecutado, asi que se narra en
seco con los resumenes del motor en vez de perder lo ocurrido.

Requiere el SDK oficial:  pip install "dnd-engine[ai]"
y una credencial: ANTHROPIC_API_KEY, o `ant auth login`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .actions import ActionResult, Intent, action_schema, execute
from .events import Event
from .game import GameEngine
from .map import distance_in_feet
from .models import Consumable, Weapon

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
NO_ACTION = "no_action"
# Tope de acciones por frase: una secuencia razonable de turno, no un guion.
MAX_INTENTS = 3
# La API se sobrecarga (429/529) y perder un turno por eso es inaceptable, asi
# que se reintenta mas que el valor por defecto del SDK.
DEFAULT_RETRIES = 5
OVERLOADED_STATUS = frozenset({429, 500, 502, 503, 504, 529})

_JSON_TYPES = {"str": "string", "int": "integer"}


class DungeonMasterError(RuntimeError):
    """Fallo al hablar con el modelo. Nunca significa que una regla fallara."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class DMTurn:
    player_message: str
    intents: tuple[Intent, ...]
    narration: str
    results: tuple[ActionResult, ...] = ()
    error: str | None = None
    events: tuple[Event, ...] = ()

    @property
    def acted(self) -> bool:
        return bool(self.results)

    @property
    def intent(self) -> Intent | None:
        """La primera intencion, para cuando solo interesa una."""
        return self.intents[0] if self.intents else None

    @property
    def result(self) -> ActionResult | None:
        return self.results[-1] if self.results else None


INTERPRETER_SYSTEM = """\
Eres el interprete de un motor de D&D. Traduces lo que dice un jugador a \
acciones del catalogo de herramientas y nada mas.

Reglas:
- Elige al menos una herramienta.
- Elige varias, en el orden en que deben ocurrir, solo cuando el jugador pide \
claramente una secuencia: "me acerco y le pego" son dos (move y attack), y \
"bebo la pocion y ataco" tambien. Maximo tres, y nunca pasos que el jugador no \
haya pedido: si dice solo "ataco", es una sola.
- Los identificadores (personajes, armas, hechizos, puertas, ubicaciones) deben \
salir literalmente del estado que se te da. No los inventes ni los traduzcas.
- Las coordenadas son casillas de la cuadricula, no pies.
- Si el jugador dice acercarse, ir a ver o aproximarse a un personaje, usa la
    herramienta approach: nunca uses move con la casilla que ocupa el objetivo.
- Si el jugador no pide una accion del juego (pregunta, charla, algo imposible \
de expresar con el catalogo), usa la herramienta no_action y explica por que.
- No decides resultados: no sabes si un ataque acierta, cuanto dano hace ni si \
una puerta cede. Eso lo resuelve el motor despues.
- Ante ambiguedad, elige la lectura mas literal de lo que ha dicho el jugador. \
Si pide algo que el estado no permite, produce igualmente la accion: el motor \
la rechazara con un motivo concreto y ese motivo es util.
- La memoria de campana sirve para resolver referencias como "el mismo goblin" o \
"vuelvo alli". Los identificadores siguen saliendo del estado actual, no de ella: \
lo que la memoria recuerda pudo dejar de ser cierto.
"""

NARRATOR_SYSTEM = """\
Eres el narrador de una partida de D&D. Escribes en espanol, en segunda persona, \
en dos o tres frases secas y concretas.

Tienes prohibido inventar hechos mecanicos. Solo puedes narrar lo que aparece en \
los datos: tiradas, dano, puntos de golpe, estados, posiciones y eventos. No \
anadas resultados, heridas, reacciones de personajes ni consecuencias que los \
datos no digan. No inventes dialogo de personajes que no han hablado.

Si la accion fue rechazada por las reglas, explica en ficcion por que no ocurre \
y deja claro que el turno sigue disponible.

Tienes la memoria de campana para dar continuidad: puedes aludir a lo ya ocurrido, \
pero solo a lo que aparezca en ella.

No repitas los numeros en bruto como un informe: usa los datos, pero escribe \
prosa. No uses listas ni encabezados.
"""


OPENING_SYSTEM = """Eres el narrador de una partida de D&D y estas abriendo la aventura. Escribe en espanol, en segunda persona, entre tres y cinco frases.

Situa al grupo: donde estan, que se respira en el sitio, y por que estan ahi. Cierra dejando claro que se juegan, sin listar objetivos como una lista.

Solo puedes usar lo que aparece en los datos. No inventes lugares, personajes, objetos ni sucesos que no figuren. No menciones comandos, reglas, dados ni nada del sistema: esto es ficcion. No hagas hablar a nadie que no sepas que ha hablado.
"""


def build_tools() -> list[dict[str, Any]]:
    """Convierte el catalogo de acciones en herramientas de la API."""
    tools: list[dict[str, Any]] = []
    for spec in action_schema():
        properties: dict[str, Any] = {}
        for parameter in spec["parameters"]:
            json_type = _JSON_TYPES[parameter["type"]]
            properties[parameter["name"]] = {
                # Los parametros opcionales se declaran anulables para poder
                # exigirlos todos, que es lo que pide el modo estricto.
                "type": json_type if parameter["required"] else [json_type, "null"],
                "description": parameter["description"],
            }
        tools.append({
            "name": spec["action"],
            "description": spec["description"],
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        })
    tools.append({
        "name": NO_ACTION,
        "description": "El jugador no pide ninguna accion ejecutable del catalogo.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Por que no hay accion."},
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
    })
    return tools


def describe_state(engine: GameEngine, actor_id: str) -> str:
    """Instantanea del estado en texto, con los identificadores que el modelo debe usar."""
    actor = engine.world.get_character(actor_id)
    location = engine.world.world.location_of(actor_id)
    lines: list[str] = []

    if location is None:
        lines.append("UBICACION: ninguna")
    else:
        grid = location.grid
        size = f"cuadricula {grid.width}x{grid.height}" if grid else "sin cuadricula"
        lines.append(f"UBICACION: {location.name} ({location.id}) - {size}")

    position = f", en {actor.position}" if location and location.grid else ""
    lines.append(
        f"TU PERSONAJE: {actor.name} ({actor.id}), {actor.hp}/{actor.max_hp} HP, "
        f"CA {actor.armor_class}{position}, estado: {_state_of(actor)}"
    )
    resources = actor.resources
    lines.append(
        f"  turno: accion {_yes(resources.action)}, adicional {_yes(resources.bonus_action)}, "
        f"reaccion {_yes(resources.reaction)}, movimiento {resources.movement} pies"
    )

    weapons = [item for item in actor.inventory if isinstance(item, Weapon)]
    lines.append("ARMAS: " + (", ".join(
        f"{weapon.id} \"{weapon.name}\" (d{weapon.damage_die}+{weapon.damage_bonus}, "
        f"alcance {weapon.reach})" for weapon in weapons) or "ninguna"))
    lines.append("HECHIZOS: " + (", ".join(
        f"{spell.id} \"{spell.name}\" (nivel {spell.level}, "
        f"{actor.spell_slots.get(spell.level, 0)} espacios, alcance {spell.range_feet})"
        for spell in actor.spells) or "ninguno"))
    others = [item for item in actor.inventory if not isinstance(item, Weapon)]
    lines.append("OBJETOS: " + (", ".join(
        f"{item.id} \"{item.name}\"" + (
            f" (usable: {item.effect.value}, {item.uses} usos)"
            if isinstance(item, Consumable) else "")
        for item in others) or "ninguno"))

    if location is not None:
        present = []
        for occupant_id in sorted(location.occupants):
            if occupant_id == actor_id:
                continue
            other = engine.world.get_character(occupant_id)
            where = ""
            if location.grid is not None:
                where = (f", en {other.position}, a "
                         f"{distance_in_feet(actor.position, other.position)} pies")
            present.append(f"  {occupant_id} \"{other.name}\" "
                           f"{other.hp}/{other.max_hp} HP{where}, {_state_of(other)}")
        lines.append("PRESENTES:\n" + ("\n".join(present) or "  nadie mas"))

        loot = []
        for item in location.items:
            where = f", en {item.cell}" if item.cell else ""
            loot.append(f"  {item.id} \"{item.name}\"{where}")
        lines.append("EN EL SUELO:\n" + ("\n".join(loot) or "  nada"))

        doors = []
        for door in engine.world.world.doors_of(location.id):
            if door.hidden:
                continue
            cell = door.cell_in(location.id)
            where = f", en la casilla {cell}" if cell else ""
            state = "cerrada con llave" if door.locked else "abierta"
            doors.append(f"  {door.id} -> {door.other_side(location.id)}, {state}{where}")
        lines.append("PUERTAS:\n" + ("\n".join(doors) or "  ninguna"))

        if location.grid is not None and location.grid.blocked:
            lines.append("CASILLAS BLOQUEADAS: " + ", ".join(
                str(cell) for cell in sorted(location.grid.blocked)))

    encounter = engine.encounter
    if encounter is not None and encounter.order:
        turn_of = encounter.order[encounter.current_index]
        lines.append(f"COMBATE: ronda {encounter.round_number}, turno de {turn_of}, "
                     f"orden {encounter.order}")
    else:
        lines.append("COMBATE: no hay ninguno activo")
    return "\n".join(lines)


def _yes(value: bool) -> str:
    return "si" if value else "no"


def _state_of(character) -> str:
    if character.is_dead:
        return "muerto"
    if character.is_dying:
        return "agonizando"
    if not character.is_conscious:
        return "inconsciente"
    if character.conditions:
        return ", ".join(sorted(condition.value for condition in character.conditions))
    return "en pie"


def describe_events(events) -> str:
    return "\n".join(
        f"  {event.type} actor={event.actor_id} objetivo={event.target_id} {event.data}"
        for event in events
    ) or "  (ninguno)"


class DungeonMaster:
    """Interprete y narrador. El motor sigue siendo la autoridad sobre las reglas."""

    def __init__(
        self,
        client: Any = None,
        model: str = MODEL,
        effort: str = "low",
        max_tokens: int = MAX_TOKENS,
        story: str = "",
    ) -> None:
        self.client = client if client is not None else _default_client()
        # La historia configurada no cambia en toda la campana, asi que va en el
        # prompt de sistema y sigue entrando en la cache.
        self.story = story
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.tools = build_tools()

    # -- ciclo completo ---------------------------------------------------

    def play(self, engine: GameEngine, actor_id: str, message: str,
             remember: bool = True) -> DMTurn:
        seen = len(engine.events.history)
        intents = self.interpret(engine, actor_id, message)

        results: list[ActionResult] = []
        error: str | None = None
        for intent in intents:
            if intent.action == NO_ACTION:
                continue
            try:
                results.append(execute(engine, intent))
            except ValueError as rule_error:
                # Se para en el primer rechazo: lo anterior ya ha ocurrido de
                # verdad y el narrador tiene que contarlo tal cual.
                error = str(rule_error)
                break

        events = tuple(engine.events.history[seen:])
        try:
            narration = self.narrate(
                engine, actor_id, message, intents, results, error, events)
        except DungeonMasterError:
            # Si la narracion falla, el turno ya se ejecuto: mejor contarlo en
            # seco que perder lo que ha pasado.
            narration = self._plain_narration(engine, actor_id, results, error)
        if remember:
            # El jugador y la narracion se apuntan despues de la accion, para que
            # la cronica de los eventos quede por delante en el orden correcto.
            engine.memory.remember_player(message)
            engine.memory.remember_narration(narration)
        return DMTurn(message, tuple(intents), narration, tuple(results), error, events)

    def _plain_narration(self, engine: GameEngine, actor_id: str,
                         results: list[ActionResult], error: str | None) -> str:
        """Salida mecanica de reserva cuando el modelo no puede narrar."""
        name = engine.world.get_character(actor_id).name
        parts = [f"{name} {one.summary}" for one in results]
        if error:
            parts.append(f"No puede ser: {error}")
        return " ".join(parts) or "No ocurre nada."

    def open_scene(self, engine: GameEngine, actor_id: str) -> str:
        """Narra la apertura de la aventura a partir del resumen de campana."""
        from .campaign import briefing

        response = self._call(
            system=self._system(OPENING_SYSTEM),
            messages=[{"role": "user", "content":
                       "Datos de la apertura:\n"
                       f"{briefing(engine, actor_id, intro='')}\n\n"
                       f"Estado inicial:\n{describe_state(engine, actor_id)}"}],
        )
        return "".join(one.text for one in response.content if one.type == "text").strip()

    # -- fase 1: interpretar ----------------------------------------------

    def interpret(self, engine: GameEngine, actor_id: str, message: str) -> list[Intent]:
        """Traduce la frase a una o varias intenciones, en orden de ejecucion.

        Se admite mas de una porque los jugadores hablan asi: "me acerco a la
        rana y le clavo la espada" son dos cosas que la economia de turno
        permite en el mismo turno (movimiento y accion).
        """
        response = self._call(
            system=self._system(INTERPRETER_SYSTEM),
            tools=self.tools,
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content":
                       f"{engine.memory.recall()}\n\n"
                       f"Estado de la partida:\n{describe_state(engine, actor_id)}\n\n"
                       f"El jugador dice: {message}"}],
        )
        blocks = [one for one in response.content if one.type == "tool_use"]
        if not blocks:
            raise DungeonMasterError(
                "El modelo no eligio ninguna accion "
                f"(stop_reason={getattr(response, 'stop_reason', None)})."
            )
        return [
            # Los parametros opcionales llegan como null; el motor los ignora.
            Intent(block.name,
                   {key: value for key, value in block.input.items() if value is not None},
                   actor_id)
            for block in blocks[:MAX_INTENTS]
        ]

    # -- fase 2: narrar ----------------------------------------------------

    def narrate(
        self,
        engine: GameEngine,
        actor_id: str,
        message: str,
        intents: list[Intent],
        results: list[ActionResult],
        error: str | None,
        events,
    ) -> str:
        lines: list[str] = []
        for one in intents:
            if one.action == NO_ACTION:
                lines.append("No hay accion que ejecutar. Motivo del interprete: "
                             f"{one.parameters.get('reason', 'sin motivo')}")
        for one in results:
            lines.append(f"RESULTADO REAL: {one.summary}\nDatos: {one.data}")
        if error is not None:
            lines.append(f"LAS REGLAS RECHAZAN LA ACCION. Motivo exacto: {error}")
        outcome = "\n".join(lines) or "No ocurre nada."

        response = self._call(
            system=self._system(NARRATOR_SYSTEM),
            messages=[{"role": "user", "content":
                       f"{engine.memory.recall()}\n\n"
                       f"El jugador dijo: {message}\n"
                       f"Acciones interpretadas, en orden: "
                       f"{[(one.action, one.parameters) for one in intents]}\n"
                       f"{outcome}\n"
                       f"Eventos publicados por el motor:\n{describe_events(events)}\n\n"
                       f"Estado tras la accion:\n{describe_state(engine, actor_id)}"}],
        )
        return "".join(one.text for one in response.content if one.type == "text").strip()

    def _system(self, base: str) -> list[dict[str, Any]]:
        return [{"type": "text", "text": base + self.story,
                 "cache_control": {"type": "ephemeral"}}]

    # -- transporte --------------------------------------------------------

    def _call(self, **parameters: Any):
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                output_config={"effort": self.effort},
                **parameters,
            )
        except Exception as error:
            translated = self._translate(error)
            if translated is None:
                raise
            raise translated from error

        if getattr(response, "stop_reason", None) == "refusal":
            raise DungeonMasterError("El modelo declino responder a esta peticion.")
        return response

    def _translate(self, error: Exception) -> DungeonMasterError | None:
        """Traduce los errores del SDK; devuelve None si el error no es suyo."""
        # Sin credencial el SDK falla al construir la peticion con un TypeError,
        # no con AuthenticationError, y sin esto la consola se caia entera.
        if isinstance(error, TypeError) and "authentication" in str(error).lower():
            return DungeonMasterError(
                "No hay credencial de Anthropic: define ANTHROPIC_API_KEY "
                "o ejecuta 'ant auth login'."
            )
        anthropic = _anthropic_module()
        if anthropic is None:
            return None
        if isinstance(error, anthropic.AuthenticationError):
            return DungeonMasterError(
                "Credencial de Anthropic invalida o ausente: define ANTHROPIC_API_KEY."
            )
        if isinstance(error, anthropic.NotFoundError):
            return DungeonMasterError(f"Modelo '{self.model}' no encontrado.")
        if isinstance(error, anthropic.APIStatusError):
            if error.status_code in OVERLOADED_STATUS:
                return DungeonMasterError(
                    f"La API esta sobrecargada ({error.status_code}) y no ha cedido "
                    "tras varios reintentos.",
                    retryable=True,
                )
            return DungeonMasterError(f"La API respondio {error.status_code}: {error.message}")
        if isinstance(error, anthropic.APIConnectionError):
            return DungeonMasterError(
                "No se pudo conectar con la API de Anthropic.", retryable=True)
        return None


def _anthropic_module():
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic


def _default_client():
    anthropic = _anthropic_module()
    if anthropic is None:
        raise DungeonMasterError(
            'El DM con IA necesita el SDK oficial: pip install "dnd-engine[ai]"'
        )
    return anthropic.Anthropic(max_retries=DEFAULT_RETRIES)
