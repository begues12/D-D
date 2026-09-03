import io

from dnd_engine.console import Console
from dnd_engine.events import Event, EventBus
from dnd_engine.game import GameEngine
from dnd_engine.map import Door, Grid
from dnd_engine.memory import CHRONICLE, NARRATION, PLAYER, CampaignMemory
from dnd_engine.models import AbilityScores, Character, Enemy, Item, Location, Objective, Quest, Weapon, World
from dnd_engine.persistence import load_game, save_game


def make_game():
    world = World("Prueba")
    world.add_location(Location("hall", "Vestibulo", grid=Grid(5, 5)))
    world.add_location(Location("vault", "Camara", grid=Grid(3, 3)))
    world.add_door(Door("iron-door", "hall", "vault", cell_a=(0, 4), cell_b=(0, 0),
                        locked=True, key_id="key"))
    engine = GameEngine(world, roller=lambda _low, high: min(high, 20))

    hero = Character("hero", "Aldric", max_hp=20, armor_class=12,
                     abilities=AbilityScores(strength=16))
    hero.add_item(Weapon("sword", "Espada", damage_die=8, damage_bonus=2, attack_bonus=3))
    hero.add_item(Item("key", "Llave"))
    engine.add_character(hero)
    engine.place("hero", "hall", (3, 4))

    goblin = Enemy("goblin", "Goblin", max_hp=8, armor_class=10, experience_reward=300)
    engine.add_character(goblin)
    engine.place("goblin", "hall", (4, 4))
    return engine


# -- captura de eventos -------------------------------------------------------


def test_notable_events_become_facts_and_chronicle():
    engine = make_game()

    engine.attack("hero", "goblin", "sword")

    memory = engine.memory
    assert memory.facts["muerte:goblin"] == "Goblin murio."
    assert memory.facts["nivel:hero"] == "Aldric alcanzo el nivel 2."
    texts = [entry.text for entry in memory.entries]
    assert "Goblin murio." in texts
    assert all(entry.kind == CHRONICLE for entry in memory.entries)


def test_noisy_events_are_not_remembered():
    engine = make_game()
    engine.start_turn("hero")
    engine.move("hero", (2, 2))
    engine.saving_throw("hero", "dexterity", 10)

    assert engine.memory.entries == []
    assert engine.memory.facts == {}


def test_locations_doors_and_quests_are_remembered():
    engine = make_game()
    engine.add_quest(Quest(
        "clear-hall", "Limpiar el vestibulo",
        objectives={"kill": Objective("kill", "Matar al goblin", "NPC_DIES", "goblin")},
    ))
    engine.unlock_door("iron-door", "hero")
    engine.move("hero", (0, 4))
    engine.use_door("hero", "iron-door")

    facts = engine.memory.facts
    assert facts["puerta:iron-door"] == "La puerta 'iron-door' fue abierta."
    assert facts["lugar:vault"] == "Aldric estuvo en Camara."
    assert "clear-hall" not in str(facts)  # la mision sigue abierta

    engine.enter_location("hero", "hall")
    # Al cruzar la puerta se aparece en su casilla, lejos del goblin.
    engine.world.get_character("hero").position = (3, 4)
    engine.attack("hero", "goblin", "sword")
    assert engine.memory.facts["mision:clear-hall"] == "La mision 'clear-hall' se completo."


def test_downed_and_revived_are_remembered():
    memory = CampaignMemory()
    bus = EventBus()
    memory.subscribe(bus)

    bus.publish(Event("CHARACTER_DOWNED", "goblin", "hero", {}))
    bus.publish(Event("CHARACTER_STABILIZED", "hero"))

    texts = [entry.text for entry in memory.entries]
    assert "hero cayo inconsciente." in texts
    assert "hero se estabilizo al borde de la muerte." in texts
    # Caer y estabilizarse no son hechos duraderos: el estado real esta en el motor.
    assert memory.facts == {}


def test_names_fall_back_to_identifiers_without_a_resolver():
    memory = CampaignMemory()
    bus = EventBus()
    memory.subscribe(bus)

    bus.publish(Event("NPC_DIES", "hero", "goblin-7", {}))

    assert memory.facts["muerte:goblin-7"] == "goblin-7 murio."


# -- turnos del jugador y del DM ----------------------------------------------


def test_player_and_narration_turns_are_recorded_in_order():
    memory = CampaignMemory()
    memory.remember_player("ataco al goblin")
    memory.remember_narration("Tu espada encuentra su hueco.")

    assert [(entry.kind, entry.text) for entry in memory.entries] == [
        (PLAYER, "ataco al goblin"),
        (NARRATION, "Tu espada encuentra su hueco."),
    ]


def test_empty_text_is_not_recorded():
    memory = CampaignMemory()
    memory.remember_narration("")

    assert memory.entries == []


# -- acotado ------------------------------------------------------------------


def test_the_chronicle_is_bounded_but_facts_are_not():
    memory = CampaignMemory(max_entries=5)
    memory.facts["muerte:dragon"] = "El dragon murio."
    for number in range(20):
        memory.remember_player(f"turno {number}")

    assert len(memory.entries) == 5
    assert memory.dropped == 15
    assert memory.entries[0].text == "turno 15"
    assert memory.facts["muerte:dragon"] == "El dragon murio."


def test_recall_shows_facts_and_the_recent_tail():
    memory = CampaignMemory(max_entries=5)
    memory.facts["muerte:dragon"] = "El dragon murio."
    for number in range(20):
        memory.remember_player(f"turno {number}")

    text = memory.recall(recent=3)

    assert "El dragon murio." in text
    assert "turno 19" in text
    assert "turno 16" not in text
    assert "hay 17 anteriores" in text


def test_recall_on_a_fresh_campaign():
    text = CampaignMemory().recall()

    assert "ninguno todavia" in text


# -- historial de eventos acotado ---------------------------------------------


def test_event_history_stops_growing_without_bound():
    bus = EventBus(history_limit=10)
    for number in range(50):
        bus.publish(Event("TURN_STARTED", "hero", data={"n": number}))

    assert len(bus.history) == 10
    assert bus.history[-1].data["n"] == 49


# -- persistencia -------------------------------------------------------------


def test_memory_survives_save_and_load(tmp_path):
    engine = make_game()
    engine.attack("hero", "goblin", "sword")
    engine.memory.remember_player("le remato")
    engine.memory.remember_narration("El goblin se derrumba.")
    path = tmp_path / "campana.json"

    save_game(engine, path)
    loaded = load_game(path)

    assert loaded.memory.facts == engine.memory.facts
    assert [entry.text for entry in loaded.memory.entries] == [
        entry.text for entry in engine.memory.entries
    ]
    assert "El goblin se derrumba." in loaded.memory.recall()


def test_a_loaded_memory_keeps_capturing_new_events(tmp_path):
    path = tmp_path / "campana.json"
    save_game(make_game(), path)

    loaded = load_game(path)
    # load_game no puede restaurar un roller inyectado: al cargar, los dados
    # vuelven a ser aleatorios. Lo fijamos para que el test sea determinista.
    loaded.combat.roller = lambda _low, high: min(high, 20)
    loaded.attack("hero", "goblin", "sword")

    assert loaded.memory.facts["muerte:goblin"] == "Goblin murio."


def test_a_loaded_memory_keeps_its_bound(tmp_path):
    engine = make_game()
    engine.memory.max_entries = 3
    for number in range(6):
        engine.memory.remember_player(f"turno {number}")
    path = tmp_path / "campana.json"

    save_game(engine, path)
    loaded = load_game(path)

    assert loaded.memory.max_entries == 3
    assert loaded.memory.dropped == 3
    assert len(loaded.memory.entries) == 3


# -- consola ------------------------------------------------------------------


def test_console_shows_the_memory():
    engine = make_game()
    engine.attack("hero", "goblin", "sword")
    console = Console(engine, "hero", io.StringIO(), io.StringIO())

    console.handle("memoria")

    text = console.stream_out.getvalue()
    assert "MEMORIA DE CAMPANA" in text
    assert "Goblin murio." in text
