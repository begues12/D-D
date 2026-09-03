from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class Event:
    type: str
    actor_id: str | None = None
    target_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


EventHandler = Callable[[Event], None]


# El historial es una cola de depuracion, no el registro de la campana: eso es
# CampaignMemory. Sin tope, una campana larga lo serializaba entero en cada
# guardado y crecia para siempre.
DEFAULT_HISTORY_LIMIT = 500


class EventBus:
    def __init__(self, history_limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self.history: list[Event] = []
        self.history_limit = history_limit

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: Event) -> None:
        self.history.append(event)
        if self.history_limit and len(self.history) > self.history_limit:
            del self.history[:-self.history_limit]
        for handler in self._handlers.get(event.type, []):
            handler(event)
