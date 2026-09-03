"""Nucleo de dominio para un motor de D&D."""

from .encounter import Encounter
from .game import GameEngine
from .map import CELL_FEET, Cell, Door, Grid, distance_in_feet
from .models import (
    Character,
    Condition,
    DeathSaves,
    Enemy,
    Item,
    Location,
    NPC,
    Objective,
    Quest,
    Spell,
    TurnResources,
    Weapon,
    World,
)
from .persistence import load_game, save_game
from .rules import Advantage

__all__ = [
    "Advantage",
    "CELL_FEET",
    "Cell",
    "Character",
    "Condition",
    "DeathSaves",
    "Door",
    "Encounter",
    "Enemy",
    "GameEngine",
    "Grid",
    "Item",
    "Location",
    "NPC",
    "Objective",
    "Quest",
    "Spell",
    "TurnResources",
    "load_game",
    "save_game",
    "distance_in_feet",
    "Weapon",
    "World",
]
