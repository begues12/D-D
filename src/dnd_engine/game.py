from __future__ import annotations

from .encounter import Encounter
from .events import Event, EventBus
from .map import Cell, Door, distance_in_feet
from .memory import CampaignMemory
from .models import Character, Consumable, Enemy, Item, Location, NPC, Quest, World
from .quest import QuestEngine
from .rules import Advantage, AttackResult, CombatRules, DeathSaveResult, ItemUseResult
from .world import MovementResult, WorldEngine


# Administrar un objeto a otro es tocarlo.
TOUCH_REACH = 5


class GameEngine:
    """Punto de entrada del dominio; no contiene interpretacion narrativa."""

    def __init__(self, world: World, roller=None) -> None:
        self.events = EventBus()
        self.world = WorldEngine(world, self.events)
        self.combat = CombatRules(self.events, roller) if roller else CombatRules(self.events)
        self.quests = QuestEngine(self.events)
        self.memory = CampaignMemory(name_of=self._display_name)
        self.memory.subscribe(self.events)
        self.encounter: Encounter | None = None
        self.events.subscribe("NPC_DIES", self._award_experience)

    def add_character(self, character: Character, location_id: str | None = None) -> None:
        self.world.world.add_character(character, location_id)

    def attack(
        self,
        attacker_id: str,
        target_id: str,
        weapon_id: str,
        advantage: Advantage = Advantage.NONE,
    ) -> AttackResult:
        attacker = self.world.get_character(attacker_id)
        target = self.world.get_character(target_id)
        weapon = attacker.get_weapon(weapon_id)
        self._require_in_range(attacker, target, weapon.reach, weapon.name)
        return self.combat.attack(attacker, target, weapon, advantage)

    def cast_spell(self, caster_id: str, target_id: str, spell_id: str):
        caster = self.world.get_character(caster_id)
        target = self.world.get_character(target_id)
        spell = caster.get_spell(spell_id)
        self._require_in_range(caster, target, spell.range_feet, spell.name)
        return self.combat.cast_spell(caster, target, spell)

    def saving_throw(self, character_id: str, ability: str, dc: int, advantage: Advantage = Advantage.NONE):
        return self.combat.saving_throw(self.world.get_character(character_id), ability, dc, advantage)

    def death_save(self, character_id: str) -> DeathSaveResult:
        return self.combat.death_save(self.world.get_character(character_id))

    def heal(self, character_id: str, amount: int) -> int:
        return self.combat.heal(self.world.get_character(character_id), amount)

    def start_turn(self, character_id: str) -> Character:
        """Unico camino de inicio de turno, dentro y fuera de un encuentro."""
        character = self.world.get_character(character_id)
        self._begin_turn(character)
        return character

    def add_enemy(self, enemy: Enemy, location_id: str | None = None) -> None:
        self.add_character(enemy, location_id)

    def place(self, character_id: str, location_id: str, cell: Cell | None = None) -> Location:
        return self.world.place(character_id, location_id, cell)

    def move(self, character_id: str, destination: Cell) -> MovementResult:
        return self.world.move(character_id, destination)

    def approach(self, character_id: str, target_id: str) -> MovementResult:
        return self.world.approach(character_id, target_id)

    def enter_location(self, character_id: str, location_id: str, force: bool = False) -> Location:
        return self.world.enter_location(character_id, location_id, force)

    def use_door(self, character_id: str, door_id: str) -> Location:
        return self.world.use_door(character_id, door_id)

    def talk(self, character_id: str, npc_id: str, said: str = "") -> tuple[NPC, str]:
        """Hablar con un PNJ presente. Devuelve el PNJ y lo que cuenta esta vez.

        No cuesta accion -hablar es gratis en el turno- y no cambia el mundo: lo
        unico que produce es un evento y una linea de lo que ese PNJ sabe. Los
        `secrets` no salen de aqui; para eso esta el DM, que decide si se sueltan.
        """
        npc = self.world.get_character(npc_id)
        if not isinstance(npc, NPC):
            raise ValueError(f"Con '{npc_id}' no se puede conversar.")
        if not npc.is_conscious:
            raise ValueError(f"{npc.name} no esta en condiciones de responder.")
        here = self.world.location_of(character_id)
        if here is None or npc_id not in here.occupants:
            raise ValueError(f"{npc.name} no esta aqui.")

        # Se va contando lo que sabe en orden, y vuelve a empezar cuando se acaba:
        # asi insistir sirve de algo y no hace falta guardar estado en el PNJ.
        knowledge = sorted(npc.knowledge)
        told = sum(1 for one in self.events.history
                   if one.type == "NPC_SPOKEN_TO" and one.target_id == npc_id)
        line = knowledge[told % len(knowledge)] if knowledge else ""
        self.events.publish(Event(
            "NPC_SPOKEN_TO", character_id, npc_id,
            {"said": said, "answer": line, "times": told + 1},
        ))
        return npc, line

    def use_item(
        self, user_id: str, item_id: str, target_id: str | None = None,
    ) -> ItemUseResult:
        """Usa un consumible sobre uno mismo o sobre alguien al alcance del brazo."""
        user = self.world.get_character(user_id)
        item = user.get_item(item_id)
        if not isinstance(item, Consumable):
            raise ValueError(f"'{item.name}' no se puede usar.")
        target = self.world.get_character(target_id) if target_id else user
        self._require_in_range(user, target, TOUCH_REACH, item.name)
        return self.combat.use_consumable(user, target, item, self.in_encounter)

    def take_item(self, character_id: str, item_id: str) -> Item:
        return self.world.take_item(character_id, item_id, self.in_encounter)

    def drop_item(self, character_id: str, item_id: str) -> Item:
        return self.world.drop_item(character_id, item_id, self.in_encounter)

    @property
    def in_encounter(self) -> bool:
        """Fuera de un encuentro no hay turnos, asi que no hay economia que gastar."""
        return self.encounter is not None

    def unlock_door(self, door_id: str, character_id: str | None = None) -> Door:
        return self.world.unlock_door(door_id, character_id)

    def distance_between(self, character_id: str, other_id: str) -> int | None:
        return self.world.distance_between(character_id, other_id)

    def add_quest(self, quest: Quest) -> None:
        self.quests.add_quest(quest)

    def begin_encounter(self, character_ids: list[str]) -> list[str]:
        participants = [self.world.get_character(character_id) for character_id in character_ids]
        self.encounter = Encounter(participants, self.events, self.combat.roller)
        return self.encounter.begin()

    def next_turn(self) -> Character:
        if self.encounter is None:
            raise ValueError("No hay un encuentro activo.")
        character = self.encounter.advance()
        self._begin_turn(character, round_number=self.encounter.round_number)
        return character

    def end_encounter(self) -> None:
        if self.encounter is not None:
            self.encounter.end()
            self.encounter = None

    def _begin_turn(self, character: Character, round_number: int | None = None) -> None:
        character.begin_turn()
        self._tick_conditions(character)
        data = {} if round_number is None else {"round": round_number}
        self.events.publish(Event("TURN_STARTED", character.id, data=data))
        if character.is_dying:
            self.combat.death_save(character)

    def _display_name(self, identifier: str) -> str:
        """Nombre legible de un personaje o una ubicacion, para la memoria."""
        character = self.world.world.characters.get(identifier)
        if character is not None:
            return character.name
        location = self.world.world.locations.get(identifier)
        return location.name if location is not None else identifier

    def _require_in_range(
        self, actor: Character, target: Character, reach_feet: int, what: str,
    ) -> None:
        """Solo se comprueba el alcance donde hay mapa; sin cuadricula no hay distancia."""
        if actor is target:
            return
        location = self.world.world.location_of(actor.id)
        target_location = self.world.world.location_of(target.id)
        if location is None or target_location is None:
            return
        if location.id != target_location.id:
            raise ValueError(f"{target.name} no esta en '{location.id}'.")
        if location.grid is None:
            return
        distance = distance_in_feet(actor.position, target.position)
        if distance > reach_feet:
            raise ValueError(
                f"{target.name} esta a {distance} pies y el alcance de {what} es {reach_feet}."
            )

    def _tick_conditions(self, character: Character) -> None:
        for condition, remaining in list(character.condition_durations.items()):
            remaining -= 1
            if remaining <= 0:
                character.condition_durations.pop(condition)
                character.conditions.discard(condition)
                self.events.publish(Event(
                    "CONDITION_EXPIRED", character.id,
                    data={"condition": condition.value},
                ))
            else:
                character.condition_durations[condition] = remaining

    def _award_experience(self, event: Event) -> None:
        if event.actor_id is None or event.target_id is None:
            return
        defeated = self.world.get_character(event.target_id)
        if not isinstance(defeated, Enemy) or defeated.experience_reward <= 0:
            return
        winner = self.world.get_character(event.actor_id)
        gained_levels = winner.gain_experience(defeated.experience_reward)
        self.events.publish(Event(
            "XP_AWARDED", winner.id, defeated.id,
            {"amount": defeated.experience_reward, "levels_gained": gained_levels},
        ))
        for level in gained_levels:
            self.events.publish(Event("LEVEL_UP", winner.id, data={"level": level}))
