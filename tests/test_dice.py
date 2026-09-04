import pytest

from dnd_engine.dice import Dice, roll_dice
from dnd_engine.models import AbilityScores, Character, Enemy, Location, Weapon, World
from dnd_engine.game import GameEngine


def sequence(values):
    """Un lanzador determinista: devuelve los valores en orden."""
    return lambda _low, _high: values.pop(0)


# -- notacion ------------------------------------------------------------

@pytest.mark.parametrize("notation, expected", [
    ("2d6+3", Dice(2, 6, 3)),
    ("1d8", Dice(1, 8)),
    ("d20", Dice(1, 20)),
    ("1d10-2", Dice(1, 10, -2)),
    (" 3d4 + 1 ", Dice(3, 4, 1)),
    ("5", Dice(0, 0, 5)),
    ("0", Dice(0, 0, 0)),
])
def test_notation_is_parsed(notation, expected):
    assert Dice.parse(notation) == expected


@pytest.mark.parametrize("notation", ["espada", "", "d", "2d", "2x6"])
def test_invalid_notation_is_rejected(notation):
    with pytest.raises(ValueError):
        Dice.parse(notation)


def test_a_dice_prints_as_its_notation():
    assert str(Dice(2, 6, 3)) == "2d6+3"
    assert str(Dice(1, 8)) == "1d8"
    assert str(Dice(1, 10, -2)) == "1d10-2"
    assert str(Dice(0, 0, 4)) == "4"


def test_parsing_a_dice_returns_the_same_dice():
    dice = Dice(2, 6, 3)
    assert Dice.parse(dice) is dice


def test_dice_reject_impossible_shapes():
    with pytest.raises(ValueError):
        Dice(-1, 6)
    with pytest.raises(ValueError):
        Dice(1, 0)


def test_a_flat_amount_forgets_the_faces():
    # Dos cantidades fijas iguales tienen que parecerlo.
    assert Dice(0, 6, 5) == Dice(0, 0, 5)
    assert Dice(0, 0, 5).is_flat


# -- rangos --------------------------------------------------------------

def test_range_and_average():
    dice = Dice(2, 6, 3)
    assert (dice.minimum, dice.maximum, dice.average) == (5, 15, 10.0)


def test_a_critical_doubles_the_dice_and_keeps_the_bonus():
    assert Dice(1, 8, 3).doubled() == Dice(2, 8, 3)
    assert Dice(0, 0, 4).doubled() == Dice(0, 0, 4)


# -- tiradas -------------------------------------------------------------

def test_rolling_keeps_every_die_visible():
    result = Dice(2, 6, 3).roll(sequence([5, 2]))

    assert result.rolls == (5, 2)
    assert result.total == 10
    assert result.detail == "2d6+3 [5,2]+3 = 10"


def test_rolling_without_bonus_omits_it():
    assert roll_dice("2d4", sequence([1, 3])).detail == "2d4 [1,3] = 4"


def test_a_flat_amount_rolls_nothing():
    result = roll_dice("7", sequence([]))

    assert result.rolls == ()
    assert result.total == 7
    assert result.detail == "7 = 7"


def test_a_liar_roller_is_caught():
    with pytest.raises(ValueError):
        Dice(1, 6).roll(sequence([9]))


# -- el motor tira los dados del arma ------------------------------------

def make_game(rolls, damage="2d6+3"):
    world = World("Test World")
    world.add_location(Location("room", "Test Room"))
    engine = GameEngine(world, roller=sequence(rolls))
    hero = Character("hero", "Hero", max_hp=10, armor_class=12,
                     abilities=AbilityScores(strength=16))
    hero.add_item(Weapon("greatsword", "Mandoble", damage=damage, attack_bonus=3))
    engine.add_character(hero, "room")
    engine.add_enemy(Enemy("enemy", "Enemy", max_hp=30, armor_class=10), "room")
    return engine


def test_a_weapon_rolls_all_of_its_dice():
    engine = make_game([12, 5, 2])

    result = engine.attack("hero", "enemy", "greatsword")

    assert result.damage_roll.rolls == (5, 2)
    assert result.damage == 10
    assert engine.world.get_character("enemy").hp == 20


def test_the_attack_event_carries_the_breakdown():
    engine = make_game([12, 5, 2])

    engine.attack("hero", "enemy", "greatsword")

    assert engine.events.history[-1].data["damage_roll"] == "2d6+3 [5,2]+3 = 10"


def test_a_missed_attack_rolls_no_damage():
    engine = make_game([2])

    result = engine.attack("hero", "enemy", "greatsword")

    assert result.hit is False
    assert result.damage_roll is None
    assert engine.events.history[-1].data["damage_roll"] is None


def test_a_weapon_accepts_a_dice_object_too():
    weapon = Weapon("club", "Garrote", damage=Dice(1, 4, 1))
    assert str(weapon.damage) == "1d4+1"
