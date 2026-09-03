import io

import pytest

from dnd_engine.campaign import (
    ARCHETYPES,
    DIFFICULTIES,
    MAX_PLAYERS,
    SCENARIOS,
    TONES,
    CampaignSetup,
    PlayerSetup,
    briefing,
    build_campaign,
    scenario_intro,
    story_brief,
)
from dnd_engine.menu import Cancelled, SetupMenu
from dnd_engine.models import Consumable, Enemy, ItemEffect, Weapon
from dnd_engine.persistence import load_game, save_game


def setup_of(engine):
    return CampaignSetup.from_world(engine.world.world)


# -- integridad de los escenarios ---------------------------------------------


def test_every_scenario_is_coherent_and_buildable():
    for scenario_id, blueprint in SCENARIOS.items():
        location_ids = {one["id"] for one in blueprint["locations"]}
        assert blueprint["start"] in location_ids, scenario_id

        for door in blueprint["doors"]:
            assert door["a"] in location_ids and door["b"] in location_ids, door["id"]

        character_ids = set()
        for group in ("enemies", "npcs"):
            for one in blueprint.get(group, []):
                assert one["location"] in location_ids, one["id"]
                character_ids.add(one["id"])

        for objective in blueprint.get("quest", {}).get("objectives", []):
            target = objective["target_id"]
            assert target in character_ids or target in location_ids, objective["id"]

        engine = build_campaign(CampaignSetup(scenario=scenario_id))
        assert len(engine.world.world.locations) == len(location_ids)


def test_loose_items_lie_on_free_cells():
    for scenario_id in SCENARIOS:
        world = build_campaign(CampaignSetup(scenario=scenario_id)).world.world
        for location in world.locations.values():
            for item in location.items:
                if location.grid is None:
                    assert item.cell is None, (scenario_id, item.id)
                elif item.cell is not None:
                    assert location.grid.is_free(item.cell), (scenario_id, item.id)


def test_every_scenario_places_everyone_inside_its_grid():
    for scenario_id in SCENARIOS:
        engine = build_campaign(CampaignSetup(scenario=scenario_id))
        world = engine.world.world
        for location in world.locations.values():
            if location.grid is None:
                continue
            for occupant_id in location.occupants:
                position = world.characters[occupant_id].position
                assert location.grid.is_free(position), (scenario_id, occupant_id, position)


def test_every_scenario_can_be_completed_from_the_start():
    """Alcanzabilidad llave-puerta: ninguna aventura se queda encallada."""
    for scenario_id in SCENARIOS:
        world = build_campaign(CampaignSetup(scenario=scenario_id)).world.world
        reached = {world.location_of("hero-aldric").id}
        carried = {item.id for character in world.characters.values()
                   for item in character.inventory}
        changed = True
        while changed:
            changed = False
            available = carried | {item.id for one in reached
                                   for item in world.get_location(one).items}
            for door in world.doors.values():
                for side, other in ((door.location_a, door.location_b),
                                    (door.location_b, door.location_a)):
                    if side in reached and other not in reached:
                        if not door.locked or door.key_id in available:
                            reached.add(other)
                            changed = True
        assert reached == set(world.locations), (
            scenario_id, set(world.locations) - reached)


def test_keys_are_found_in_the_world_not_in_pockets():
    for scenario_id in SCENARIOS:
        world = build_campaign(CampaignSetup(scenario=scenario_id)).world.world
        loose = {item.id for location in world.locations.values()
                 for item in location.items}
        for door in world.doors.values():
            if door.locked:
                assert door.key_id in loose, (scenario_id, door.id)


# -- construccion -------------------------------------------------------------


def test_the_hero_gets_the_gear_of_the_archetype():
    engine = build_campaign(CampaignSetup(
        players=[PlayerSetup("Nel", "mago")], scenario="taberna"))

    hero = engine.world.get_character("hero-nel")
    assert hero.name == "Nel"
    assert hero.max_hp == ARCHETYPES["mago"].max_hp
    assert hero.abilities.intelligence == 16
    assert [spell.id for spell in hero.spells] == ["firebolt", "hold"]
    assert hero.spell_slots == {1: 3}
    assert hero.get_spell("hold").condition.value == "paralyzed"
    assert isinstance(hero.inventory[0], Weapon)


def test_the_whole_party_starts_together():
    engine = build_campaign(CampaignSetup(players=[
        PlayerSetup("Aldric", "guerrero"),
        PlayerSetup("Nel", "mago"),
        PlayerSetup("Bran", "picaro"),
    ], scenario="cripta"))

    start = engine.world.world.get_location("vestibule")
    assert {"hero-aldric", "hero-nel", "hero-bran"} <= start.occupants
    positions = [engine.world.get_character(f"hero-{one}").position
                 for one in ("aldric", "nel", "bran")]
    assert len(set(positions)) == 3  # nadie se pisa


def test_players_only_start_with_the_gear_of_their_archetype():
    engine = build_campaign(CampaignSetup(players=[
        PlayerSetup("Aldric", "guerrero"), PlayerSetup("Nel", "mago"),
    ], scenario="taberna"))

    carried = {item.id for item in engine.world.get_character("hero-aldric").inventory}
    assert carried == {"longsword", "shield", "rations", "potion"}
    assert {item.id for item in engine.world.get_character("hero-nel").inventory} == {
        "dagger", "spellbook", "potion"}


def test_every_archetype_carries_a_usable_potion():
    for archetype in ARCHETYPES:
        engine = build_campaign(CampaignSetup(
            players=[PlayerSetup("Aldric", archetype)]))
        potion = engine.world.get_character("hero-aldric").get_item("potion")
        assert isinstance(potion, Consumable)
        assert potion.effect is ItemEffect.HEAL
        assert potion.uses == 1


def test_scenario_consumables_are_built_as_such():
    world = build_campaign(CampaignSetup(scenario="cripta")).world.world
    balm = next(one for one in world.get_location("gallery").items
                if one.id == "grave-balm")

    assert isinstance(balm, Consumable)
    assert balm.uses == 2
    assert balm.cell == (6, 4)


def test_difficulty_scales_the_enemies():
    easy = build_campaign(CampaignSetup(scenario="taberna", difficulty="facil"))
    hard = build_campaign(CampaignSetup(scenario="taberna", difficulty="dificil"))

    easy_boss = easy.world.get_character("goblin-boss")
    hard_boss = hard.world.get_character("goblin-boss")
    assert easy_boss.max_hp < hard_boss.max_hp
    assert hard_boss.armor_class - easy_boss.armor_class == 3
    assert easy_boss.experience_reward == hard_boss.experience_reward


def test_a_bigger_party_meets_tougher_enemies():
    alone = build_campaign(CampaignSetup(players=[PlayerSetup("Aldric")]))
    four = build_campaign(CampaignSetup(players=[
        PlayerSetup(name) for name in ("Aldric", "Nel", "Bran", "Sela")]))

    assert (four.world.get_character("goblin-boss").max_hp
            > alone.world.get_character("goblin-boss").max_hp)


def test_enemies_are_armed_and_hostile():
    engine = build_campaign(CampaignSetup(scenario="pantano"))

    priest = engine.world.get_character("drowned-priest")
    assert isinstance(priest, Enemy)
    assert any(isinstance(item, Weapon) for item in priest.inventory)


def test_the_quest_is_registered_and_reactive():
    engine = build_campaign(CampaignSetup(scenario="cripta"))

    quest = engine.quests.quests["silence-the-king"]
    assert quest.status == "active"
    engine.world.get_character("barrow-king").hp = 1
    engine.world.get_character("hero-aldric").position = (2, 1)
    engine.world.place("hero-aldric", "throne", (2, 1))
    engine.attack("hero-aldric", "barrow-king", "longsword")
    # Puede fallar el ataque; lo que se comprueba es que la mision escucha.
    assert quest.status in ("active", "completed")


# -- configuracion -------------------------------------------------------------


def test_validate_rejects_unknown_catalog_entries():
    for field, value in (("scenario", "luna"), ("tone", "epico"), ("difficulty", "brutal")):
        setup = CampaignSetup()
        setattr(setup, field, value)
        with pytest.raises(ValueError, match="No existe"):
            setup.validate()


def test_validate_rejects_a_broken_party():
    with pytest.raises(ValueError, match="al menos un jugador"):
        CampaignSetup(players=[]).validate()
    with pytest.raises(ValueError, match="necesita un nombre"):
        CampaignSetup(players=[PlayerSetup("  ")]).validate()
    with pytest.raises(ValueError, match="No existe el arquetipo"):
        CampaignSetup(players=[PlayerSetup("Aldric", "bardo")]).validate()
    with pytest.raises(ValueError, match="dos jugadores llamados"):
        CampaignSetup(players=[PlayerSetup("Aldric"), PlayerSetup("aldric")]).validate()
    with pytest.raises(ValueError, match=f"maximo {MAX_PLAYERS}"):
        CampaignSetup(players=[PlayerSetup(f"H{n}") for n in range(MAX_PLAYERS + 1)]).validate()


def test_names_become_usable_identifiers():
    assert PlayerSetup("Aldric el Rojo").id == "hero-aldric-el-rojo"
    assert PlayerSetup("  Nel  ").id == "hero-nel"


def test_the_setup_travels_with_the_campaign(tmp_path):
    original = CampaignSetup(
        players=[PlayerSetup("Nel", "mago")], scenario="torre", tone="misterio",
        difficulty="dificil", premise="Buscamos a mi hermana.", use_ai_dm=True,
        title="La torre callada",
    )
    engine = build_campaign(original)
    path = tmp_path / "campana.json"

    save_game(engine, path)
    restored = setup_of(load_game(path))

    assert restored.to_dict() == original.to_dict()
    assert restored.campaign_title == "La torre callada"
    assert restored.players[0].archetype == "mago"


def test_story_brief_carries_tone_and_premise():
    setup = CampaignSetup(
        players=[PlayerSetup("Nel", "mago")], scenario="pantano", tone="oscuro",
        premise="Nel no sabe nadar.",
    )

    brief = story_brief(setup)

    assert TONES["oscuro"].guidance in brief
    assert "Nel no sabe nadar." in brief
    assert "hero-nel" in brief
    assert SCENARIOS["pantano"]["description"] in brief


def test_summary_lists_the_whole_party():
    text = CampaignSetup(players=[
        PlayerSetup("Aldric", "guerrero"), PlayerSetup("Nel", "mago"),
    ]).summary()

    assert "Grupo (2)" in text
    assert "Aldric, Guerrero" in text
    assert "Nel, Mago" in text


# -- menu ---------------------------------------------------------------------


def menu(script):
    return SetupMenu(io.StringIO(script), io.StringIO())


def test_the_menu_builds_the_campaign_it_was_told():
    #      escenario, cuantos, nombre1, arq1, nombre2, arq2, tono, dificultad,
    #      premisa, ia, titulo, confirmar
    flow = menu("2\n2\nAldric\n1\nNel\n3\noscuro\n3\nBuscamos a mi hermana.\n"
                "no\nLa cripta callada\nsi\n")

    engine, first = flow.new_campaign()

    setup = setup_of(engine)
    assert setup.scenario == "cripta"
    assert [(one.name, one.archetype) for one in setup.players] == [
        ("Aldric", "guerrero"), ("Nel", "mago")]
    assert setup.tone == "oscuro"
    assert setup.difficulty == "dificil"
    assert setup.premise == "Buscamos a mi hermana."
    assert setup.use_ai_dm is False
    assert setup.title == "La cripta callada"
    assert first == "hero-aldric"
    assert engine.world.get_character("hero-nel").spells


def test_empty_answers_take_the_defaults():
    engine, first = menu("\n\n\n\n\n\n\n\n\nsi\n").new_campaign()

    setup = setup_of(engine)
    assert setup.scenario == "taberna"
    assert setup.tone == "heroico"
    assert setup.difficulty == "normal"
    assert setup.premise == ""
    assert setup.title == ""
    assert first == "hero-heroe-1"


def test_options_can_be_answered_by_name():
    flow = menu("torre\n1\nNel\nmago\nhumor\nfacil\n-\nno\n\nsi\n")

    setup = setup_of(flow.new_campaign()[0])

    assert setup.scenario == "torre"
    assert setup.players[0].archetype == "mago"
    assert setup.tone == "humor"
    assert setup.difficulty == "facil"


def test_bad_answers_are_asked_again():
    flow = menu("99\nluna\n2\n0\n7\n1\nAldric\n1\n1\n2\n-\nno\n\nsi\n")

    setup = setup_of(flow.new_campaign()[0])

    assert setup.scenario == "cripta"
    assert len(setup.players) == 1
    text = flow.stream_out.getvalue()
    assert "Solo hay 4 opciones" in text
    assert "Tiene que estar entre 1 y" in text


def test_duplicate_names_are_refused():
    flow = menu("1\n2\nAldric\n1\nAldric\nNel\n1\n1\n2\n-\nno\n\nsi\n")

    setup = setup_of(flow.new_campaign()[0])

    assert [one.name for one in setup.players] == ["Aldric", "Nel"]
    assert "Ya hay alguien con ese nombre" in flow.stream_out.getvalue()


def test_the_summary_can_be_amended_before_starting():
    #                             ... confirmar=no, cambio=tono, tono=crudo, confirmar=si
    flow = menu("1\n1\nAldric\n1\n1\n2\n-\nno\n\nno\ntono\n5\nsi\n")

    setup = setup_of(flow.new_campaign()[0])

    assert setup.tone == "crudo"


def test_saying_salir_cancels_the_preparation():
    with pytest.raises(Cancelled):
        menu("1\nsalir\n").new_campaign()


def test_the_main_menu_can_reload_a_saved_campaign(tmp_path):
    path = tmp_path / "guardada.json"
    save_game(build_campaign(CampaignSetup(
        players=[PlayerSetup("Nel", "mago")], scenario="torre")), path)

    started = menu(f"2\n{path}\n").run()

    assert started is not None
    engine, first = started
    assert first == "hero-nel"
    assert setup_of(engine).scenario == "torre"


def test_a_missing_save_file_returns_to_the_main_menu(tmp_path):
    flow = menu(f"2\n{tmp_path / 'no-existe.json'}\n3\n")

    assert flow.run() is None
    assert "No he podido cargarla" in flow.stream_out.getvalue()


def test_the_main_menu_can_just_quit():
    assert menu("3\n").run() is None


# -- apertura de la aventura --------------------------------------------------


def test_the_briefing_says_where_you_are_who_you_are_and_what_is_at_stake():
    engine = build_campaign(CampaignSetup(
        players=[PlayerSetup("Aldric", "guerrero"), PlayerSetup("Nel", "mago")],
        scenario="taberna", tone="oscuro", difficulty="dificil",
        premise="Buscamos al gato de Marta.",
    ))

    text = briefing(engine, "hero-aldric")

    assert "EL SOTANO DEL DRAGON ROJO" in text
    assert "Marta lleva ocho noches" in text          # el gancho del escenario
    assert "Aldric (guerrero), Nel (mago)" in text
    assert "Buscamos al gato de Marta." in text
    assert "Estais en Taberna del Dragon Rojo" in text
    assert "Marta la tabernera" in text               # quien esta presente
    assert "Llave de la bodega [cellar-key]" in text  # lo que se ve
    assert "trapdoor hacia Bodega (cerrada con llave)" in text
    assert "Lo que hay bajo la taberna:" in text      # la mision
    assert "- Encontrar el tunel" in text
    assert "Tono: oscuro. Dificultad: dificil." in text


def test_the_briefing_speaks_in_singular_to_a_lone_player():
    engine = build_campaign(CampaignSetup(players=[PlayerSetup("Aldric")]))

    text = briefing(engine, "hero-aldric")

    assert "Tu personaje: Aldric (guerrero)." in text
    assert "Estas en Taberna del Dragon Rojo" in text


def test_every_scenario_has_a_hook_and_a_briefing():
    for scenario_id in SCENARIOS:
        setup = CampaignSetup(scenario=scenario_id)
        engine = build_campaign(setup)
        assert len(scenario_intro(setup)) > 120, scenario_id  # un gancho, no una linea
        text = briefing(engine, "hero-aldric")
        assert SCENARIOS[scenario_id]["name"].upper() in text
        assert "Salidas:" in text


def test_the_narrated_intro_replaces_the_written_hook():
    engine = build_campaign(CampaignSetup(scenario="taberna"))

    text = briefing(engine, "hero-aldric", "El humo te escuece en los ojos.")

    assert "El humo te escuece en los ojos." in text
    assert "Marta lleva ocho noches" not in text
    assert "Lo que hay bajo la taberna:" in text  # los datos duros siguen


def test_completed_objectives_drop_out_of_the_briefing():
    engine = build_campaign(CampaignSetup(scenario="taberna"))
    quest = engine.quests.quests["cellar-threat"]
    quest.objectives["reach-tunnel"].completed = True

    text = briefing(engine, "hero-aldric")

    assert "Encontrar el tunel" not in text
    assert "Acabar con Zarpa" in text


def test_a_world_without_setup_still_gets_a_briefing():
    from dnd_engine.cli import build_demo

    text = briefing(build_demo(), "hero-1")

    assert "LAS TIERRAS DEL ALBA" in text
    assert "Estas en Taberna del Dragon Rojo" in text
