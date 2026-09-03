"""Memoria de campana: lo que hay que recordar dentro de veinte sesiones.

Se suscribe al bus y no sabe nada de combate ni de narrativa. Guarda dos cosas
distintas a proposito:

- `facts`: hechos duraderos, indexados por clave. No caducan nunca y son lo que
  sobrevive a cualquier recorte. Que el goblin murio sigue siendo cierto dentro
  de cien turnos.
- `entries`: la cronica reciente, acotada. Sucesos, lo que dijo el jugador y lo
  que narro el DM, en orden. Cuando se llena, lo viejo se cae; los hechos no.

Esa division es lo que permite que `recall()` quepa en un prompt sin perder lo
que importa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .events import Event, EventBus

CHRONICLE = "cronica"
PLAYER = "jugador"
NARRATION = "dm"

DEFAULT_MAX_ENTRIES = 80
DEFAULT_RECENT = 14


@dataclass
class MemoryEntry:
    kind: str
    text: str


@dataclass
class CampaignMemory:
    max_entries: int = DEFAULT_MAX_ENTRIES
    entries: list[MemoryEntry] = field(default_factory=list)
    facts: dict[str, str] = field(default_factory=dict)
    dropped: int = 0
    # Traduce identificadores a nombres legibles. Lo inyecta GameEngine para no
    # acoplar la memoria al mundo.
    name_of: Callable[[str], str] | None = None

    # -- captura ----------------------------------------------------------

    def subscribe(self, event_bus: EventBus) -> None:
        for event_type in _HANDLERS:
            event_bus.subscribe(event_type, self.handle)

    def handle(self, event: Event) -> None:
        handler = _HANDLERS.get(event.type)
        if handler is None:
            return
        remembered = handler(self, event)
        if remembered is None:
            return
        key, text = remembered
        if key is not None:
            self.facts[key] = text
        self.record(CHRONICLE, text)

    def record(self, kind: str, text: str) -> None:
        if not text:
            return
        self.entries.append(MemoryEntry(kind, text))
        while len(self.entries) > self.max_entries:
            self.entries.pop(0)
            self.dropped += 1

    def remember_player(self, text: str) -> None:
        self.record(PLAYER, text)

    def remember_narration(self, text: str) -> None:
        self.record(NARRATION, text)

    # -- consulta ----------------------------------------------------------

    def recall(self, recent: int = DEFAULT_RECENT) -> str:
        """Bloque de memoria para el prompt: hechos duraderos y cronica reciente."""
        lines = ["MEMORIA DE CAMPANA"]
        if self.facts:
            lines.append("Hechos establecidos:")
            lines.extend(f"  - {text}" for text in sorted(self.facts.values()))
        else:
            lines.append("Hechos establecidos: ninguno todavia.")

        tail = self.entries[-recent:] if recent > 0 else []
        if tail:
            older = self.dropped + len(self.entries) - len(tail)
            heading = "Ultimos sucesos:"
            if older:
                heading = f"Ultimos sucesos (hay {older} anteriores, ya resumidos arriba):"
            lines.append(heading)
            lines.extend(f"  [{entry.kind}] {entry.text}" for entry in tail)
        else:
            lines.append("Ultimos sucesos: ninguno todavia.")
        return "\n".join(lines)

    def _name(self, identifier: str | None) -> str:
        if identifier is None:
            return "alguien"
        if self.name_of is None:
            return identifier
        return self.name_of(identifier)

    # -- persistencia ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_entries": self.max_entries,
            "dropped": self.dropped,
            "facts": self.facts,
            "entries": [{"kind": entry.kind, "text": entry.text} for entry in self.entries],
        }

    def load(self, data: dict[str, Any]) -> None:
        """Vuelca un estado guardado sobre esta instancia, ya suscrita al bus."""
        self.max_entries = data.get("max_entries", DEFAULT_MAX_ENTRIES)
        self.dropped = data.get("dropped", 0)
        self.facts = dict(data.get("facts", {}))
        self.entries = [
            MemoryEntry(entry["kind"], entry["text"]) for entry in data.get("entries", [])
        ]


# -- traduccion de eventos a memoria ------------------------------------------
#
# Solo lo que seguira importando mas tarde. Ataques, movimientos, turnos y
# tiradas sueltas no entran: son ruido que llenaria la cronica en dos combates.


def _died(memory: CampaignMemory, event: Event):
    return f"muerte:{event.target_id}", f"{memory._name(event.target_id)} murio."


def _downed(memory: CampaignMemory, event: Event):
    return None, f"{memory._name(event.target_id)} cayo inconsciente."


def _stabilized(memory: CampaignMemory, event: Event):
    return None, f"{memory._name(event.actor_id)} se estabilizo al borde de la muerte."


def _revived(memory: CampaignMemory, event: Event):
    return None, f"{memory._name(event.actor_id)} volvio en si."


def _level_up(memory: CampaignMemory, event: Event):
    level = event.data.get("level")
    return (f"nivel:{event.actor_id}",
            f"{memory._name(event.actor_id)} alcanzo el nivel {level}.")


def _entered(memory: CampaignMemory, event: Event):
    location_id = event.data.get("location_id")
    return (f"lugar:{location_id}",
            f"{memory._name(event.actor_id)} estuvo en {memory._name(location_id)}.")


def _door_unlocked(memory: CampaignMemory, event: Event):
    door_id = event.data.get("door_id")
    return f"puerta:{door_id}", f"La puerta '{door_id}' fue abierta."


def _quest_completed(memory: CampaignMemory, event: Event):
    quest_id = event.data.get("quest_id")
    return f"mision:{quest_id}", f"La mision '{quest_id}' se completo."


def _quest_failed(memory: CampaignMemory, event: Event):
    quest_id = event.data.get("quest_id")
    return f"mision:{quest_id}", f"La mision '{quest_id}' se malogro."


def _objective(memory: CampaignMemory, event: Event):
    return None, (f"Objetivo '{event.data.get('objective_id')}' cumplido "
                  f"en la mision '{event.data.get('quest_id')}'.")


def _combat_ended(memory: CampaignMemory, event: Event):
    return None, f"Termino un combate en la ronda {event.data.get('round')}."


_HANDLERS: dict[str, Callable[[CampaignMemory, Event], tuple[str | None, str] | None]] = {
    "NPC_DIES": _died,
    "CHARACTER_DOWNED": _downed,
    "CHARACTER_STABILIZED": _stabilized,
    "CHARACTER_REVIVED": _revived,
    "LEVEL_UP": _level_up,
    "PLAYER_ENTERED_LOCATION": _entered,
    "DOOR_UNLOCKED": _door_unlocked,
    "QUEST_COMPLETED": _quest_completed,
    "QUEST_FAILED": _quest_failed,
    "QUEST_OBJECTIVE_COMPLETED": _objective,
    "COMBAT_ENDED": _combat_ended,
}
