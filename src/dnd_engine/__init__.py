"""Nucleo de dominio para un motor de D&D."""

from .dice import Dice, DiceRoll, roll_dice
from .encounter import Encounter
from .forge import Pitch, ScenarioError, ScenarioForge, validate_scenario
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
from .providers import PROVIDERS, Provider, get_provider
from .rules import Advantage

__all__ = [
    "Advantage",
    "CELL_FEET",
    "Cell",
    "Character",
    "Condition",
    "DeathSaves",
    "Dice",
    "DiceRoll",
    "Door",
    "Encounter",
    "Enemy",
    "GameEngine",
    "Grid",
    "Item",
    "Location",
    "NPC",
    "PROVIDERS",
    "Pitch",
    "Provider",
    "Objective",
    "Quest",
    "ScenarioError",
    "ScenarioForge",
    "Spell",
    "TurnResources",
    "load_game",
    "roll_dice",
    "save_game",
    "validate_scenario",
    "distance_in_feet",
    "get_provider",
    "Weapon",
    "World",
]
