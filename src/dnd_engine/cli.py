from .game import GameEngine
from .map import Grid
from .models import AbilityScores, Character, Enemy, Item, Location, Objective, Quest, Weapon, World


def build_demo() -> GameEngine:
    world = World("Las Tierras del Alba")
    # La taberna es teatro de la mente; la bodega tiene cuadricula y barriles.
    world.add_location(Location("red-dragon-tavern", "Taberna del Dragon Rojo"))
    world.add_location(Location(
        "cellar", "Bodega", grid=Grid(6, 4, {(2, 1), (2, 2), (4, 0)}),
    ))
    world.connect(
        "red-dragon-tavern", "cellar", "trapdoor",
        cell_b=(0, 0), locked=True, key_id="cellar-key",
    )

    engine = GameEngine(world)
    hero = Character(
        "hero-1", "Aldric", max_hp=18, armor_class=14,
        abilities=AbilityScores(strength=16, dexterity=12),
    )
    hero.add_item(Weapon("longsword", "Espada larga", damage="1d8+3", attack_bonus=5))
    hero.add_item(Item("cellar-key", "Llave de la bodega"))
    engine.add_character(hero, "red-dragon-tavern")

    goblin = Enemy("goblin-1", "Goblin", max_hp=9, armor_class=13, experience_reward=50,
                   abilities=AbilityScores(strength=12, dexterity=14))
    goblin.add_item(Weapon("scimitar", "Cimitarra", damage="1d6+1", attack_bonus=4))
    engine.add_enemy(goblin)
    engine.place("goblin-1", "cellar", (5, 3))

    engine.add_quest(Quest(
        "goblin-threat", "Amenaza goblin",
        objectives={"defeat": Objective("defeat", "Derrotar al goblin", "NPC_DIES", "goblin-1")},
    ))
    return engine


def main() -> None:
    engine = build_demo()

    engine.unlock_door("trapdoor", "hero-1")
    engine.enter_location("hero-1", "cellar")
    engine.start_turn("hero-1")
    print(f"Aldric baja a la bodega en {engine.world.get_character('hero-1').position}.")
    print(f"El goblin esta a {engine.distance_between('hero-1', 'goblin-1')} pies.")

    movement = engine.move("hero-1", (4, 3))
    print(f"Avanza {movement.cost_feet} pies rodeando los barriles "
          f"(le quedan {movement.movement_left}).")

    result = engine.attack("hero-1", "goblin-1", "longsword")
    print(f"Ataque: d20={result.natural_roll}, total={result.total_attack}")
    print("Resultado:", "impacto critico" if result.critical else "impacto" if result.hit else "fallo")
    print(f"Dano: {result.damage_roll}; HP del objetivo: {result.target_hp}")
    print("Eventos:", ", ".join(event.type for event in engine.events.history))
    print("Estado de mision:", engine.quests.quests["goblin-threat"].status)
