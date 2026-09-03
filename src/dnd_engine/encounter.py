from __future__ import annotations

from dataclasses import dataclass

from .events import Event, EventBus
from .models import Character
from .rules import Roller


@dataclass
class Encounter:
    """Lleva el orden de iniciativa. No inicia turnos: eso lo hace GameEngine."""

    participants: list[Character]
    event_bus: EventBus
    roller: Roller
    order: list[str] | None = None
    current_index: int = -1
    round_number: int = 0

    def begin(self) -> list[str]:
        initiatives = {
            character.id: self.roller(1, 20) + character.abilities.modifier("dexterity")
            for character in self.participants
        }
        self.order = [character.id for character in sorted(
            self.participants,
            key=lambda character: (
                initiatives[character.id],
                character.abilities.dexterity,
                character.id,
            ),
            reverse=True,
        )]
        self.current_index = -1
        self.round_number = 0
        self.event_bus.publish(Event("COMBAT_STARTED", data={
            "order": self.order.copy(), "initiatives": initiatives,
        }))
        return self.order.copy()

    def advance(self) -> Character:
        """Devuelve el siguiente participante vivo, saltando a los muertos.

        Los personajes inconscientes pero vivos si reciben turno: es cuando
        tiran su salvacion contra muerte.
        """
        if not self.order:
            raise ValueError("El encuentro no ha comenzado.")
        for _ in range(len(self.order)):
            self.current_index = (self.current_index + 1) % len(self.order)
            if self.current_index == 0:
                self.round_number += 1
            character = self._participant(self.order[self.current_index])
            if character.is_alive:
                return character
            self.event_bus.publish(Event(
                "TURN_SKIPPED", character.id, data={"round": self.round_number},
            ))
        raise ValueError("Ningun participante sigue en pie.")

    def end(self) -> None:
        self.event_bus.publish(Event("COMBAT_ENDED", data={"round": self.round_number}))
        self.order = None
        self.current_index = -1

    def _participant(self, character_id: str) -> Character:
        return next(
            character for character in self.participants if character.id == character_id
        )
