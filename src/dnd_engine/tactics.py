"""Tactica deterministica para personajes no controlados.

Es un marcador de posicion a proposito: acercarse al enemigo mas cercano y
golpear. No es "IA" en ningun sentido interesante, pero permite jugar un combate
entero desde la consola sin tener que llevar tambien a los monstruos. Cuando
llegue el DM basado en IA, sustituira a esta funcion produciendo intenciones.
"""

from __future__ import annotations

from .actions import ActionResult, Intent, execute
from .game import GameEngine
from .map import distance_in_feet
from .models import Character, Enemy, Weapon


def is_hostile(actor: Character, other: Character) -> bool:
    """Bando por tipo: los enemigos van contra todo lo demas, y viceversa."""
    return isinstance(actor, Enemy) != isinstance(other, Enemy)


def take_turn(engine: GameEngine, character_id: str) -> list[ActionResult]:
    """Ejecuta el turno completo del personaje y devuelve lo que hizo."""
    actor = engine.world.get_character(character_id)
    if not actor.can_act or not actor.is_conscious:
        return []
    location = engine.world.world.location_of(character_id)
    if location is None:
        return []

    target = _closest_target(engine, actor, location.id)
    if target is None:
        return []

    weapon = next((item for item in actor.inventory if isinstance(item, Weapon)), None)
    if weapon is None:
        return []

    results: list[ActionResult] = []
    if location.grid is not None:
        cell = _best_approach(engine, actor, target, location.id, weapon.reach)
        if cell is not None and cell != actor.position:
            results.append(execute(engine, Intent("move", {"x": cell[0], "y": cell[1]}, actor.id)))
        if distance_in_feet(actor.position, target.position) > weapon.reach:
            return results

    results.append(execute(engine, Intent("attack", {"target": target.id}, actor.id)))
    return results


def _closest_target(engine: GameEngine, actor: Character, location_id: str) -> Character | None:
    location = engine.world.world.get_location(location_id)
    candidates = [
        engine.world.get_character(occupant)
        for occupant in sorted(location.occupants)
        if occupant != actor.id
    ]
    hostiles = [
        other for other in candidates
        if other.is_alive and other.is_conscious and is_hostile(actor, other)
    ]
    if not hostiles:
        return None
    if location.grid is None:
        return hostiles[0]
    return min(hostiles, key=lambda other: distance_in_feet(actor.position, other.position))


def _best_approach(engine: GameEngine, actor: Character, target: Character,
                   location_id: str, reach: int):
    """La casilla alcanzable este turno que mas acerca al objetivo."""
    grid = engine.world.world.get_location(location_id).grid
    occupied = engine.world.world.occupied_cells(location_id, ignore=actor.id)
    best = actor.position
    best_distance = distance_in_feet(actor.position, target.position)
    for cell in grid.free_cells(occupied):
        path = grid.path(actor.position, cell, occupied)
        if path is None or len(path) * 5 > actor.resources.movement:
            continue
        distance = distance_in_feet(cell, target.position)
        if distance < best_distance:
            best, best_distance = cell, distance
            if distance <= reach:
                break
    return best
