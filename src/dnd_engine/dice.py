"""Sistema de dados: notacion `XdY+Z`, tiradas y su desglose.

El motor no vuelve a tirar un dado suelto para el dano: pide una tirada a un
`Dice` y recibe un `DiceRoll` con los valores individuales, de modo que la
consola, la interfaz y el DM narren lo que de verdad salio en la mesa.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Callable

Roller = Callable[[int, int], int]

# "2d6+3", "d8", "1d10-1", "5" (cantidad fija sin dados).
_NOTATION = re.compile(
    r"""^\s*
        (?:(?P<count>\d*)\s*[dD]\s*(?P<sides>\d+))?   # la parte de dados es opcional
        \s*(?P<bonus>[+-]\s*\d+)?\s*$
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Dice:
    """Una expresion de dados inmutable: `count` dados de `sides` caras mas `bonus`."""

    count: int = 1
    sides: int = 6
    bonus: int = 0

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("Un numero de dados no puede ser negativo.")
        if self.count and self.sides < 1:
            raise ValueError("Un dado debe tener al menos una cara.")
        if not self.count:
            # Una cantidad fija se normaliza para que dos expresiones iguales lo parezcan.
            object.__setattr__(self, "sides", 0)

    @classmethod
    def parse(cls, notation: str | "Dice") -> "Dice":
        """Lee `2d6+3`, `d20`, `1d8-1` o `4` (cantidad fija)."""
        if isinstance(notation, Dice):
            return notation
        text = str(notation).strip()
        if re.fullmatch(r"[+-]?\d+", text):
            # Una cantidad fija se escribe tal cual: "5", "0".
            return cls(0, 0, int(text))
        match = _NOTATION.match(text)
        if match is None or not match.group("sides") and not match.group("bonus"):
            raise ValueError(f"Notacion de dados invalida: '{notation}'.")
        sides = match.group("sides")
        if sides is None:
            return cls(0, 0, int(match.group("bonus").replace(" ", "")))
        count = match.group("count")
        bonus = match.group("bonus")
        return cls(
            int(count) if count else 1,
            int(sides),
            int(bonus.replace(" ", "")) if bonus else 0,
        )

    @property
    def is_flat(self) -> bool:
        """Una cantidad fija: no hay nada que tirar."""
        return self.count == 0

    @property
    def minimum(self) -> int:
        return self.count + self.bonus

    @property
    def maximum(self) -> int:
        return self.count * self.sides + self.bonus

    @property
    def average(self) -> float:
        return self.count * (self.sides + 1) / 2 + self.bonus

    def doubled(self) -> "Dice":
        """Un critico duplica los dados, nunca el bonus."""
        return Dice(self.count * 2, self.sides, self.bonus)

    def plus(self, bonus: int) -> "Dice":
        return Dice(self.count, self.sides, self.bonus + bonus)

    def roll(self, roller: Roller = random.randint) -> "DiceRoll":
        rolls = tuple(roll_die(self.sides, roller) for _ in range(self.count))
        return DiceRoll(self, rolls, sum(rolls) + self.bonus)

    def __str__(self) -> str:
        if self.is_flat:
            return str(self.bonus)
        text = f"{self.count}d{self.sides}"
        if self.bonus:
            text += f"{self.bonus:+d}"
        return text


@dataclass(frozen=True)
class DiceRoll:
    """El resultado de una tirada, con los dados individuales a la vista."""

    dice: Dice
    rolls: tuple[int, ...]
    total: int

    @property
    def detail(self) -> str:
        """`2d6+3 [5,2]+3 = 10`, lo que se le ensena a quien juega."""
        if self.dice.is_flat:
            return f"{self.dice} = {self.total}"
        text = f"{self.dice} [{','.join(str(value) for value in self.rolls)}]"
        if self.dice.bonus:
            text += f"{self.dice.bonus:+d}"
        return f"{text} = {self.total}"

    def __str__(self) -> str:
        return self.detail


def roll_die(sides: int, roller: Roller = random.randint) -> int:
    """Un unico dado. Comprueba al lanzador para que un mock no falsee el juego."""
    if sides < 1:
        raise ValueError("Un dado debe tener al menos una cara.")
    result = roller(1, sides)
    if not 1 <= result <= sides:
        raise ValueError("El lanzador devolvio un resultado fuera del dado.")
    return result


def roll_dice(notation: str | Dice, roller: Roller = random.randint) -> DiceRoll:
    """Atajo para tirar directamente de una notacion: `roll_dice("2d6+3")`."""
    return Dice.parse(notation).roll(roller)
