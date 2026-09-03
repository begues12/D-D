import pytest

from dnd_engine.game import GameEngine
from dnd_engine.persistence import load_game, save_game
from dnd_engine.models import (
    AbilityScores,
    Character,
    Condition,
    Enemy,
    Location,
    Objective,
    Quest,
    Spell,
    TurnResources,
    Weapon,
    World,
)
from dnd_engine.rules import Advantage


def make_game(rolls):
    world = World("Test World")
    world.add_location(Location("room", "Test Room"))
    engine = GameEngine(world, roller=lambda _low, _high: rolls.pop(0))
    hero = Character("hero", "Hero", max_hp=10, armor_class=12, abilities=AbilityScores(strength=16))
    hero.add_item(Weapon("sword", "Sword", damage_die=8, damage_bonus=2, attack_bonus=3))
    engine.add_character(hero, "room")
    engine.add_enemy(Enemy("enemy", "Enemy", max_hp=10, armor_class=15), "room")
    return engine


def down_hero(engine):
    """Deja al heroe agonizando sin pasar por el combate."""
    hero = engine.world.get_character("hero")
    hero.hp = 0
    hero.conditions.add(Condition.UNCONSCIOUS)
    return hero


def test_attack_hit_reduces_hp_and_publishes_event():
    engine = make_game([12, 5])

    result = engine.attack("hero", "enemy", "sword")

    assert result.total_attack == 18
    assert result.hit is True
    assert result.damage == 7
    assert engine.world.get_character("enemy").hp == 3
    assert [event.type for event in engine.events.history] == ["PLAYER_ATTACK"]


def test_critical_rolls_damage_twice():
    engine = make_game([20, 4, 6])

    result = engine.attack("hero", "enemy", "sword")

    assert result.critical is True
    assert result.damage == 14
    assert engine.world.get_character("enemy").hp == 0
    assert [event.type for event in engine.events.history] == ["PLAYER_ATTACK", "NPC_DIES"]


def test_natural_one_is_always_a_miss():
    engine = make_game([1])

    result = engine.attack("hero", "enemy", "sword")

    assert result.hit is False
    assert result.damage == 0
    assert engine.world.get_character("enemy").hp == 10


def test_unknown_location_is_rejected():
    engine = make_game([])

    with pytest.raises(ValueError, match="no existe"):
        engine.world.enter_location("hero", "missing")


def test_quest_completes_objectives_from_world_events():
    engine = make_game([20, 4, 6])
    engine.add_quest(Quest(
        "goblin", "Derrotar al goblin",
        objectives={"defeat": Objective("defeat", "Derrotar enemigo", "NPC_DIES", "enemy")},
    ))

    engine.attack("hero", "enemy", "sword")

    assert engine.quests.quests["goblin"].status == "completed"
    assert engine.events.history[-1].type == "QUEST_COMPLETED"


def test_spell_applies_damage_and_condition_when_save_fails():
    engine = make_game([5, 6])
    hero = engine.world.get_character("hero")
    hero.spells.append(Spell(
        "frost", "Rayo helado", damage_die=8, saving_ability="dexterity",
        save_dc=15, condition=Condition.STUNNED,
    ))
    hero.spell_slots[1] = 1

    result = engine.cast_spell("hero", "enemy", "frost")

    assert result.saved is False
    assert result.damage == 6
    assert Condition.STUNNED in engine.world.get_character("enemy").conditions
    assert engine.events.history[-1].type == "SPELL_CAST"


def test_timed_condition_expires_on_start_turn():
    engine = make_game([5, 6])
    hero = engine.world.get_character("hero")
    hero.spells.append(Spell(
        "stun", "Aturdir", saving_ability="dexterity", save_dc=15,
        condition=Condition.STUNNED, duration_rounds=1,
    ))
    hero.spell_slots[1] = 1
    engine.cast_spell("hero", "enemy", "stun")

    engine.start_turn("enemy")

    enemy = engine.world.get_character("enemy")
    assert Condition.STUNNED not in enemy.conditions
    assert engine.events.history[-2].type == "CONDITION_EXPIRED"


def test_timed_condition_expires_inside_an_encounter():
    engine = make_game([5, 18, 10])
    hero = engine.world.get_character("hero")
    hero.spells.append(Spell(
        "stun", "Aturdir", saving_ability="dexterity", save_dc=15,
        condition=Condition.STUNNED, duration_rounds=1,
    ))
    hero.spell_slots[1] = 1
    engine.cast_spell("hero", "enemy", "stun")

    engine.begin_encounter(["hero", "enemy"])
    engine.next_turn()
    engine.next_turn()

    enemy = engine.world.get_character("enemy")
    assert Condition.STUNNED not in enemy.conditions
    assert "CONDITION_EXPIRED" in [event.type for event in engine.events.history]


def test_saving_throw_publishes_result():
    engine = make_game([14])

    result = engine.saving_throw("enemy", "dexterity", 12)

    assert result.success is True
    assert result.total == 14
    assert engine.events.history[-1].type == "SAVING_THROW"


def test_begin_turn_restores_the_whole_turn_economy():
    engine = make_game([])
    hero = engine.world.get_character("hero")
    hero.resources.action = False
    hero.resources.bonus_action = False
    hero.resources.reaction = False
    hero.resources.object_interaction = False
    hero.resources.movement = 0

    engine.start_turn("hero")

    assert hero.resources == TurnResources(movement=hero.speed)
    assert engine.events.history[-1].type == "TURN_STARTED"


def test_encounter_orders_turns_and_advances_rounds():
    engine = make_game([18, 10])

    order = engine.begin_encounter(["hero", "enemy"])
    first = engine.next_turn()
    second = engine.next_turn()
    third = engine.next_turn()

    assert order == ["hero", "enemy"]
    assert first.id == "hero"
    assert second.id == "enemy"
    assert third.id == "hero"
    assert engine.encounter.round_number == 2


def test_encounter_skips_dead_participants():
    engine = make_game([20, 4, 6, 18, 10])
    engine.attack("hero", "enemy", "sword")

    engine.begin_encounter(["hero", "enemy"])
    first = engine.next_turn()
    second = engine.next_turn()

    assert first.id == "hero"
    assert second.id == "hero"
    assert engine.encounter.round_number == 2
    assert "TURN_SKIPPED" in [event.type for event in engine.events.history]


def test_defeating_enemy_awards_xp_and_levels_up():
    engine = make_game([20, 8, 8])
    enemy = engine.world.get_character("enemy")
    enemy.experience_reward = 300

    engine.attack("hero", "enemy", "sword")

    hero = engine.world.get_character("hero")
    assert hero.experience == 300
    assert hero.level == 2
    assert hero.max_hp == 11
    assert [event.type for event in engine.events.history[-3:]] == [
        "NPC_DIES", "XP_AWARDED", "LEVEL_UP",
    ]


def test_requested_advantage_takes_the_higher_roll():
    engine = make_game([6, 14, 5])

    result = engine.attack("hero", "enemy", "sword", Advantage.ADVANTAGE)

    assert result.rolls == (6, 14)
    assert result.natural_roll == 14
    assert result.advantage is Advantage.ADVANTAGE


def test_condition_on_target_grants_advantage_to_the_attacker():
    engine = make_game([3, 17, 4])
    engine.world.get_character("enemy").conditions.add(Condition.STUNNED)

    result = engine.attack("hero", "enemy", "sword")

    assert result.advantage is Advantage.ADVANTAGE
    assert result.natural_roll == 17
    assert result.hit is True


def test_poisoned_attacker_rolls_with_disadvantage():
    engine = make_game([17, 3])
    engine.world.get_character("hero").conditions.add(Condition.POISONED)

    result = engine.attack("hero", "enemy", "sword")

    assert result.advantage is Advantage.DISADVANTAGE
    assert result.natural_roll == 3
    assert result.hit is False


def test_advantage_and_disadvantage_cancel_out():
    engine = make_game([12, 5])
    engine.world.get_character("hero").conditions.add(Condition.POISONED)
    engine.world.get_character("enemy").conditions.add(Condition.STUNNED)

    result = engine.attack("hero", "enemy", "sword")

    assert result.advantage is Advantage.NONE
    assert result.rolls == (12,)
    assert result.damage == 7


def test_incapacitated_attacker_cannot_act():
    engine = make_game([])
    engine.world.get_character("hero").conditions.add(Condition.STUNNED)

    with pytest.raises(ValueError, match="no puede actuar"):
        engine.attack("hero", "enemy", "sword")


def test_incapacitated_character_automatically_fails_dexterity_saves():
    engine = make_game([])
    engine.world.get_character("enemy").conditions.add(Condition.PARALYZED)

    result = engine.saving_throw("enemy", "dexterity", 5)

    assert result.success is False
    assert result.automatic_failure is True
    assert engine.events.history[-1].data["automatic_failure"] is True


def test_player_character_is_downed_instead_of_killed():
    engine = make_game([20, 8, 8])
    enemy = engine.world.get_character("enemy")
    enemy.add_item(Weapon("club", "Club", damage_die=8, damage_bonus=2, attack_bonus=3))
    hero = engine.world.get_character("hero")
    hero.hp = 3

    engine.attack("enemy", "hero", "club")

    assert hero.hp == 0
    assert hero.is_dead is False
    assert hero.is_alive is True
    assert Condition.UNCONSCIOUS in hero.conditions
    assert engine.events.history[-1].type == "CHARACTER_DOWNED"


def test_damage_to_a_downed_character_adds_death_save_failures():
    engine = make_game([15, 3, 5])
    enemy = engine.world.get_character("enemy")
    enemy.add_item(Weapon("club", "Club", damage_die=8, damage_bonus=2, attack_bonus=3))
    hero = down_hero(engine)

    result = engine.attack("enemy", "hero", "club")

    assert result.advantage is Advantage.ADVANTAGE
    assert hero.hp == 0
    assert hero.death_saves.failures == 1
    assert hero.is_dead is False


def test_three_death_save_successes_stabilize():
    engine = make_game([15, 15, 15])
    hero = down_hero(engine)

    for _ in range(3):
        result = engine.death_save("hero")

    assert result.stabilized is True
    assert hero.is_stable is True
    assert hero.is_alive is True
    assert engine.events.history[-1].type == "CHARACTER_STABILIZED"


def test_three_death_save_failures_kill_the_character():
    engine = make_game([5, 5, 5])
    hero = down_hero(engine)

    for _ in range(3):
        result = engine.death_save("hero")

    assert result.dead is True
    assert hero.is_dead is True
    assert hero.is_alive is False
    assert engine.events.history[-1].type == "NPC_DIES"


def test_natural_one_death_save_counts_twice():
    engine = make_game([1])
    hero = down_hero(engine)

    engine.death_save("hero")

    assert hero.death_saves.failures == 2
    assert hero.is_dead is False


def test_natural_twenty_death_save_revives_at_one_hp():
    engine = make_game([20])
    hero = down_hero(engine)

    result = engine.death_save("hero")

    assert result.revived is True
    assert hero.hp == 1
    assert Condition.UNCONSCIOUS not in hero.conditions
    assert engine.events.history[-1].type == "CHARACTER_REVIVED"


def test_downed_character_rolls_a_death_save_on_their_turn():
    engine = make_game([18, 10, 15])
    hero = down_hero(engine)

    engine.begin_encounter(["hero", "enemy"])
    engine.next_turn()

    assert hero.death_saves.successes == 1
    assert [event.type for event in engine.events.history[-2:]] == ["TURN_STARTED", "DEATH_SAVE"]


def test_healing_a_downed_character_revives_them():
    engine = make_game([])
    hero = down_hero(engine)
    hero.death_saves.failures = 2

    healed = engine.heal("hero", 5)

    assert healed == 5
    assert hero.hp == 5
    assert hero.death_saves.failures == 0
    assert Condition.UNCONSCIOUS not in hero.conditions
    assert [event.type for event in engine.events.history] == ["HEALED", "CHARACTER_REVIVED"]


def test_save_and_load_preserves_campaign_state(tmp_path):
    engine = make_game([20, 8, 8])
    engine.world.world.state["king_alive"] = False
    engine.world.get_character("hero").experience = 250
    hero = engine.world.get_character("hero")
    hero.resources.bonus_action = False
    hero.death_saves.failures = 1
    path = tmp_path / "campaign.json"

    save_game(engine, path)
    loaded = load_game(path)

    loaded_hero = loaded.world.get_character("hero")
    assert loaded.world.world.name == "Test World"
    assert loaded.world.world.state["king_alive"] is False
    assert loaded_hero.experience == 250
    assert loaded_hero.get_weapon("sword").name == "Sword"
    assert loaded_hero.resources.bonus_action is False
    assert loaded_hero.death_saves.failures == 1
    assert loaded_hero.dies_at_zero_hp is False
    assert loaded.world.get_character("enemy").dies_at_zero_hp is True
