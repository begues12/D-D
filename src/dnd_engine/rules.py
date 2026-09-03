from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .events import Event, EventBus
from .models import (
    ATTACKER_ADVANTAGE_CONDITIONS,
    AUTOFAIL_SAVE_ABILITIES,
    DEATH_SAVE_DC,
    DEATH_SAVE_LIMIT,
    SELF_DISADVANTAGE_CONDITIONS,
    Character,
    Condition,
    Consumable,
    ItemEffect,
    Spell,
    Weapon,
)


Roller = Callable[[int, int], int]


class Advantage(str, Enum):
    NONE = "none"
    ADVANTAGE = "advantage"
    DISADVANTAGE = "disadvantage"

    @staticmethod
    def combine(advantage: bool, disadvantage: bool) -> "Advantage":
        """Ventaja y desventaja se cancelan, sin importar cuantas fuentes haya."""
        if advantage == disadvantage:
            return Advantage.NONE
        return Advantage.ADVANTAGE if advantage else Advantage.DISADVANTAGE


def roll(sides: int, roller: Roller = random.randint) -> int:
    if sides < 1:
        raise ValueError("Un dado debe tener al menos una cara.")
    result = roller(1, sides)
    if not 1 <= result <= sides:
        raise ValueError("El lanzador devolvio un resultado fuera del dado.")
    return result


@dataclass(frozen=True)
class D20Roll:
    natural: int
    rolls: tuple[int, ...]
    advantage: Advantage


def roll_d20(roller: Roller = random.randint, advantage: Advantage = Advantage.NONE) -> D20Roll:
    if advantage is Advantage.NONE:
        rolls = (roll(20, roller),)
    else:
        rolls = (roll(20, roller), roll(20, roller))
    natural = min(rolls) if advantage is Advantage.DISADVANTAGE else max(rolls)
    return D20Roll(natural, rolls, advantage)


def attack_advantage(attacker: Character, target: Character, base: Advantage = Advantage.NONE) -> Advantage:
    """Combina la ventaja pedida por quien llama con la que imponen las condiciones."""
    has_advantage = base is Advantage.ADVANTAGE or bool(target.conditions & ATTACKER_ADVANTAGE_CONDITIONS)
    has_disadvantage = base is Advantage.DISADVANTAGE or bool(attacker.conditions & SELF_DISADVANTAGE_CONDITIONS)
    return Advantage.combine(has_advantage, has_disadvantage)


@dataclass(frozen=True)
class AttackResult:
    attacker_id: str
    target_id: str
    natural_roll: int
    total_attack: int
    hit: bool
    critical: bool
    damage: int
    target_hp: int
    advantage: Advantage = Advantage.NONE
    rolls: tuple[int, ...] = ()


@dataclass(frozen=True)
class SpellResult:
    caster_id: str
    target_id: str
    saving_roll: int
    saved: bool
    damage: int
    target_hp: int
    condition_applied: Condition | None
    automatic_failure: bool = False


@dataclass(frozen=True)
class SavingThrowResult:
    character_id: str
    ability: str
    natural_roll: int
    total: int
    success: bool
    automatic_failure: bool = False
    advantage: Advantage = Advantage.NONE


@dataclass(frozen=True)
class ItemUseResult:
    user_id: str
    target_id: str
    item_id: str
    item_name: str
    effect: str
    healed: int = 0
    cured: str | None = None
    uses_left: int = 0
    spent: bool = False


@dataclass(frozen=True)
class DeathSaveResult:
    character_id: str
    natural_roll: int
    success: bool
    successes: int
    failures: int
    stabilized: bool
    revived: bool
    dead: bool


class CombatRules:
    def __init__(self, event_bus: EventBus, roller: Roller = random.randint) -> None:
        self.event_bus = event_bus
        self.roller = roller

    def attack(
        self,
        attacker: Character,
        target: Character,
        weapon: Weapon,
        advantage: Advantage = Advantage.NONE,
    ) -> AttackResult:
        if not attacker.can_act:
            raise ValueError("El atacante no puede actuar.")
        if not target.is_alive:
            raise ValueError("El objetivo ya no esta activo.")
        if not attacker.resources.action:
            raise ValueError("El atacante ya ha usado su accion.")

        d20 = roll_d20(self.roller, attack_advantage(attacker, target, advantage))
        total_attack = d20.natural + weapon.attack_bonus + attacker.abilities.modifier("strength")
        critical = d20.natural == 20
        hit = critical or (d20.natural != 1 and total_attack >= target.armor_class)
        damage = 0
        if hit:
            damage = roll(weapon.damage_die, self.roller) + weapon.damage_bonus
            if critical:
                damage += roll(weapon.damage_die, self.roller) + weapon.damage_bonus
            self._apply_damage(target, damage, critical)
        attacker.resources.action = False

        result = AttackResult(
            attacker.id, target.id, d20.natural, total_attack, hit, critical,
            damage, target.hp, d20.advantage, d20.rolls,
        )
        self.event_bus.publish(Event(
            "PLAYER_ATTACK", attacker.id, target.id,
            {"natural_roll": d20.natural, "total_attack": total_attack, "hit": hit,
             "critical": critical, "damage": damage, "advantage": d20.advantage.value},
        ))
        if hit:
            self._resolve_hp_state(attacker.id, target, damage)
        return result

    def cast_spell(self, caster: Character, target: Character, spell: Spell) -> SpellResult:
        if not caster.can_act:
            raise ValueError("El lanzador no puede actuar.")
        if not target.is_alive:
            raise ValueError("El objetivo ya no esta activo.")
        if not caster.resources.action:
            raise ValueError("El lanzador ya ha usado su accion.")
        available_slots = caster.spell_slots.get(spell.level, 0)
        if available_slots < 1:
            raise ValueError(f"No quedan espacios de nivel {spell.level}.")

        caster.spell_slots[spell.level] = available_slots - 1
        save = self._resolve_save(target, spell.saving_ability, spell.save_dc)
        damage = 0
        if spell.damage_die is not None and not save.success:
            damage = roll(spell.damage_die, self.roller) + spell.damage_bonus
            self._apply_damage(target, damage, critical=False)
        condition_applied = None
        if spell.condition is not None and not save.success:
            target.conditions.add(spell.condition)
            if spell.duration_rounds > 0:
                target.condition_durations[spell.condition] = spell.duration_rounds
            condition_applied = spell.condition
        caster.resources.action = False

        result = SpellResult(
            caster.id, target.id, save.total, save.success, damage, target.hp,
            condition_applied, save.automatic_failure,
        )
        self.event_bus.publish(Event(
            "SPELL_CAST", caster.id, target.id,
            {"spell_id": spell.id, "saving_roll": save.total, "saved": save.success,
             "automatic_failure": save.automatic_failure, "damage": damage,
             "condition": condition_applied.value if condition_applied else None},
        ))
        if damage:
            self._resolve_hp_state(caster.id, target, damage)
        return result

    def saving_throw(
        self,
        character: Character,
        ability: str,
        dc: int,
        advantage: Advantage = Advantage.NONE,
    ) -> SavingThrowResult:
        result = self._resolve_save(character, ability, dc, advantage)
        self.event_bus.publish(Event(
            "SAVING_THROW", character.id,
            data={"ability": ability, "dc": dc, "natural_roll": result.natural_roll,
                  "total": result.total, "success": result.success,
                  "automatic_failure": result.automatic_failure},
        ))
        return result

    def death_save(self, character: Character) -> DeathSaveResult:
        if character.is_dead:
            raise ValueError("El personaje ya esta muerto.")
        if character.hp > 0:
            raise ValueError("El personaje no esta agonizando.")
        if character.is_stable:
            raise ValueError("El personaje ya esta estabilizado.")

        natural = roll(20, self.roller)
        saves = character.death_saves
        revived = False
        if natural == 20:
            character.hp = 1
            character.conditions.discard(Condition.UNCONSCIOUS)
            saves.reset()
            revived = True
        elif natural == 1:
            saves.failures += 2
        elif natural >= DEATH_SAVE_DC:
            saves.successes += 1
        else:
            saves.failures += 1

        stabilized = False
        dead = False
        if not revived and saves.failures >= DEATH_SAVE_LIMIT:
            dead = True
        elif not revived and saves.successes >= DEATH_SAVE_LIMIT:
            stabilized = True
            character.is_stable = True
            saves.reset()

        result = DeathSaveResult(
            character.id, natural, natural >= DEATH_SAVE_DC,
            saves.successes, saves.failures, stabilized, revived, dead,
        )
        self.event_bus.publish(Event(
            "DEATH_SAVE", character.id,
            data={"natural_roll": natural, "successes": saves.successes,
                  "failures": saves.failures, "stabilized": stabilized,
                  "revived": revived, "dead": dead},
        ))
        if revived:
            self.event_bus.publish(Event("CHARACTER_REVIVED", character.id, data={"hp": character.hp}))
        elif stabilized:
            self.event_bus.publish(Event("CHARACTER_STABILIZED", character.id))
        elif dead:
            self._kill(None, character, 0)
        return result

    def use_consumable(
        self, user: Character, target: Character, item: Consumable,
        enforce_economy: bool = True,
    ) -> ItemUseResult:
        """Beber o administrar un consumible. En combate cuesta la accion."""
        if not user.can_act:
            raise ValueError("El personaje no puede usar objetos.")
        if item.uses < 1:
            raise ValueError(f"'{item.name}' ya esta agotado.")
        if enforce_economy and not user.resources.action:
            raise ValueError("Ya has usado tu accion este turno.")
        if not target.is_alive:
            raise ValueError(f"{target.name} ya no esta activo.")

        healed, cured = 0, None
        if item.effect is ItemEffect.HEAL:
            if target.hp >= target.max_hp:
                # No gastar el frasco para curar cero.
                raise ValueError(f"{target.name} ya esta a puntos de golpe completos.")
            amount = item.bonus + (roll(item.dice, self.roller) if item.dice else 0)
            healed = self.heal(target, amount)
        else:
            if item.condition is None or item.condition not in target.conditions:
                # Mejor rechazarlo que gastar el antidoto por una mala lectura.
                raise ValueError(
                    f"{target.name} no sufre el estado que cura '{item.name}'."
                )
            target.conditions.discard(item.condition)
            target.condition_durations.pop(item.condition, None)
            cured = item.condition.value
            self.event_bus.publish(Event(
                "CONDITION_CURED", user.id, target.id, {"condition": cured},
            ))

        item.uses -= 1
        if enforce_economy:
            user.resources.action = False
        spent = item.uses <= 0
        if spent:
            user.inventory.remove(item)
        self.event_bus.publish(Event(
            "ITEM_USED", user.id, target.id,
            {"item_id": item.id, "item_name": item.name, "effect": item.effect.value,
             "healed": healed, "cured": cured, "uses_left": item.uses},
        ))
        return ItemUseResult(user.id, target.id, item.id, item.name, item.effect.value,
                             healed, cured, item.uses, spent)

    def heal(self, character: Character, amount: int) -> int:
        if amount < 0:
            raise ValueError("La curacion no puede ser negativa.")
        if character.is_dead:
            raise ValueError("No se puede curar a un personaje muerto.")
        healed = min(amount, character.max_hp - character.hp)
        was_down = character.hp == 0
        character.hp += healed
        self.event_bus.publish(Event("HEALED", character.id, data={"amount": healed, "hp": character.hp}))
        if was_down and character.hp > 0:
            character.conditions.discard(Condition.UNCONSCIOUS)
            character.death_saves.reset()
            character.is_stable = False
            self.event_bus.publish(Event("CHARACTER_REVIVED", character.id, data={"hp": character.hp}))
        return healed

    def _resolve_save(
        self,
        character: Character,
        ability: str,
        dc: int,
        advantage: Advantage = Advantage.NONE,
    ) -> SavingThrowResult:
        """Calcula una salvacion sin publicar eventos, para reutilizarla desde hechizos."""
        if character.is_incapacitated and ability.lower() in AUTOFAIL_SAVE_ABILITIES:
            return SavingThrowResult(character.id, ability, 0, 0, False, automatic_failure=True)
        if character.conditions & SELF_DISADVANTAGE_CONDITIONS:
            advantage = Advantage.combine(advantage is Advantage.ADVANTAGE, True)
        d20 = roll_d20(self.roller, advantage)
        total = d20.natural + character.abilities.modifier(ability)
        return SavingThrowResult(character.id, ability, d20.natural, total, total >= dc, False, d20.advantage)

    def _apply_damage(self, target: Character, amount: int, critical: bool) -> None:
        """Golpear a alguien que ya esta a 0 HP suma fallos de salvacion contra muerte."""
        if amount <= 0:
            return
        if target.hp == 0 and not target.is_dead:
            target.death_saves.failures += 2 if critical else 1
            target.is_stable = False
            return
        target.hp = max(0, target.hp - amount)

    def _resolve_hp_state(self, source_id: str | None, target: Character, damage: int) -> None:
        if target.is_dead:
            return
        if target.death_saves.failures >= DEATH_SAVE_LIMIT:
            self._kill(source_id, target, damage)
            return
        if target.hp > 0 or Condition.UNCONSCIOUS in target.conditions:
            return
        if target.dies_at_zero_hp:
            self._kill(source_id, target, damage)
            return
        target.conditions.add(Condition.UNCONSCIOUS)
        target.is_stable = False
        target.death_saves.reset()
        self.event_bus.publish(Event("CHARACTER_DOWNED", source_id, target.id, {"damage": damage}))

    def _kill(self, source_id: str | None, target: Character, damage: int) -> None:
        target.hp = 0
        target.is_dead = True
        target.is_stable = False
        target.conditions.add(Condition.UNCONSCIOUS)
        self.event_bus.publish(Event("NPC_DIES", source_id, target.id, {"damage": damage}))
