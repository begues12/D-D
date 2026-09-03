from __future__ import annotations

from .events import Event, EventBus
from .models import Objective, Quest


class QuestEngine:
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus
        self.quests: dict[str, Quest] = {}

    def add_quest(self, quest: Quest) -> None:
        if quest.id in self.quests:
            raise ValueError(f"La mision '{quest.id}' ya existe.")
        self.quests[quest.id] = quest
        event_types = {objective.event_type for objective in self._all_objectives(quest)}
        event_types.update(quest.fail_event_types)
        for event_type in event_types:
            self.event_bus.subscribe(event_type, self._handle_event)

    def _all_objectives(self, quest: Quest) -> list[Objective]:
        return [*quest.objectives.values(), *quest.optional_objectives.values()]

    def _handle_event(self, event: Event) -> None:
        for quest in self.quests.values():
            if quest.status != "active":
                continue
            if event.type in quest.fail_event_types:
                quest.status = "failed"
                self.event_bus.publish(Event("QUEST_FAILED", data={"quest_id": quest.id}))
                continue
            for objective in self._all_objectives(quest):
                if self._matches(objective, event):
                    objective.completed = True
                    self.event_bus.publish(Event(
                        "QUEST_OBJECTIVE_COMPLETED",
                        data={"quest_id": quest.id, "objective_id": objective.id},
                    ))
            if quest.objectives and all(objective.completed for objective in quest.objectives.values()):
                quest.status = "completed"
                self.event_bus.publish(Event("QUEST_COMPLETED", data={"quest_id": quest.id}))

    @staticmethod
    def _matches(objective: Objective, event: Event) -> bool:
        if objective.completed or objective.event_type != event.type:
            return False
        return objective.target_id is None or objective.target_id in {
            event.actor_id, event.target_id, event.data.get("location_id")
        }
