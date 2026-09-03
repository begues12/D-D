from __future__ import annotations

from dataclasses import dataclass

from .events import Event, EventBus
from .map import CELL_FEET, Cell, Door, are_adjacent, distance_in_feet
from .models import Character, Item, Location, World


@dataclass(frozen=True)
class MovementResult:
    character_id: str
    origin: Cell
    destination: Cell
    path: tuple[Cell, ...]
    cost_feet: int
    movement_left: int


class WorldEngine:
    def __init__(self, world: World, event_bus: EventBus) -> None:
        self.world = world
        self.event_bus = event_bus

    def get_character(self, character_id: str) -> Character:
        try:
            return self.world.characters[character_id]
        except KeyError as error:
            raise ValueError(f"El personaje '{character_id}' no existe.") from error

    def location_of(self, character_id: str) -> Location:
        location = self.world.location_of(character_id)
        if location is None:
            raise ValueError(f"El personaje '{character_id}' no esta en ninguna ubicacion.")
        return location

    def place(self, character_id: str, location_id: str, cell: Cell | None = None) -> Location:
        """Coloca a un personaje saltandose puertas y movimiento: para montar la escena."""
        character = self.get_character(character_id)
        self.world.move_character(character_id, location_id)
        location = self.world.get_location(location_id)
        character.position = self._entry_cell(location, character_id, cell)
        return location

    def move(self, character_id: str, destination: Cell) -> MovementResult:
        """Mueve dentro de la ubicacion actual, validando muros, ocupantes y presupuesto."""
        character = self.get_character(character_id)
        if not character.can_act:
            raise ValueError("El personaje no puede moverse.")
        location = self.location_of(character_id)
        if location.grid is None:
            raise ValueError(f"La ubicacion '{location.id}' no tiene cuadricula.")

        grid = location.grid
        if not grid.contains(destination):
            raise ValueError(f"La casilla {destination} esta fuera de '{location.id}'.")
        occupied = self.world.occupied_cells(location.id, ignore=character_id)
        if destination in grid.blocked:
            raise ValueError(f"La casilla {destination} esta bloqueada.")
        if destination in occupied:
            raise ValueError(f"La casilla {destination} ya esta ocupada.")

        origin = character.position
        path = grid.path(origin, destination, occupied)
        if path is None:
            raise ValueError(f"No hay camino hasta {destination}.")
        cost = len(path) * CELL_FEET
        if cost > character.resources.movement:
            raise ValueError(
                f"Se necesitan {cost} pies y solo quedan {character.resources.movement}."
            )

        character.resources.movement -= cost
        character.position = destination
        result = MovementResult(
            character_id, origin, destination, tuple(path), cost, character.resources.movement,
        )
        self.event_bus.publish(Event(
            "CHARACTER_MOVED", character_id,
            data={"location_id": location.id, "origin": list(origin),
                  "destination": list(destination), "cost_feet": cost,
                  "movement_left": character.resources.movement},
        ))
        return result

    def approach(self, character_id: str, target_id: str) -> MovementResult:
        """Acerca a un personaje a otro sin intentar ocupar su casilla."""
        character = self.get_character(character_id)
        target = self.get_character(target_id)
        location = self.location_of(character_id)
        target_location = self.location_of(target_id)
        if location.id != target_location.id:
            raise ValueError(f"{target.name} no esta en '{location.id}'.")
        if location.grid is None:
            raise ValueError(f"La ubicacion '{location.id}' no tiene cuadricula.")
        if character_id == target_id:
            raise ValueError("No puedes acercarte a ti mismo.")
        if location.grid and distance_in_feet(character.position, target.position) <= CELL_FEET:
            return MovementResult(character.id, character.position, character.position, (), 0, character.resources.movement)

        occupied = self.world.occupied_cells(location.id, ignore=character_id)
        candidates = []
        for offset_x, offset_y in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            candidate = (target.position[0] + offset_x, target.position[1] + offset_y)
            path = location.grid.path(character.position, candidate, occupied)
            if path is not None and len(path) * CELL_FEET <= character.resources.movement:
                candidates.append((len(path), candidate[1], candidate[0], candidate))
        if not candidates:
            raise ValueError(f"No hay una casilla libre accesible junto a {target.name}.")
        destination = min(candidates)[-1]
        return self.move(character_id, destination)

    def enter_location(self, character_id: str, location_id: str, force: bool = False) -> Location:
        """Cambia de ubicacion. Sin `force` exige una puerta abierta que las conecte."""
        character = self.get_character(character_id)
        destination = self.world.get_location(location_id)
        current = self.world.location_of(character_id)
        door: Door | None = None
        if not force and current is not None and current.id != location_id:
            door = self.world.door_between(current.id, location_id)
            if door is None:
                raise ValueError(
                    f"No hay ninguna puerta entre '{current.id}' y '{location_id}'."
                )
            self._require_open(door)
        return self._traverse(character, destination, door)

    def use_door(self, character_id: str, door_id: str) -> Location:
        """Cruza una puerta concreta, exigiendo estar junto a ella si hay cuadricula."""
        character = self.get_character(character_id)
        if not character.can_act:
            raise ValueError("El personaje no puede cruzar la puerta.")
        door = self.world.get_door(door_id)
        current = self.location_of(character_id)
        if not door.connects(current.id):
            raise ValueError(f"La puerta '{door_id}' no da a '{current.id}'.")
        self._require_open(door)

        near_cell = door.cell_in(current.id)
        if current.grid is not None and near_cell is not None:
            if not are_adjacent(character.position, near_cell):
                raise ValueError(
                    f"Hay que estar junto a la puerta '{door_id}' en {near_cell} para cruzarla."
                )
        destination = self.world.get_location(door.other_side(current.id))
        return self._traverse(character, destination, door)

    def items_in(self, location_id: str) -> list[Item]:
        return list(self.world.get_location(location_id).items)

    def take_item(self, character_id: str, item_id: str,
                  enforce_economy: bool = True) -> Item:
        """Coge un objeto del suelo. En combate gasta la interaccion del turno."""
        character = self.get_character(character_id)
        if not character.can_act:
            raise ValueError("El personaje no puede coger nada.")
        location = self.location_of(character_id)
        item = next((one for one in location.items if one.id == item_id), None)
        if item is None:
            raise ValueError(f"Aqui no hay ningun '{item_id}'.")
        if location.grid is not None and item.cell is not None:
            if not are_adjacent(character.position, item.cell):
                raise ValueError(
                    f"'{item.name}' esta en {item.cell} y hay que estar al lado."
                )
        if enforce_economy and not character.resources.object_interaction:
            raise ValueError("Ya has manipulado un objeto este turno.")

        location.items.remove(item)
        item.cell = None
        character.add_item(item)
        if enforce_economy:
            character.resources.object_interaction = False
        self.event_bus.publish(Event(
            "ITEM_TAKEN", character_id,
            data={"item_id": item.id, "item_name": item.name, "location_id": location.id},
        ))
        return item

    def drop_item(self, character_id: str, item_id: str,
                  enforce_economy: bool = True) -> Item:
        character = self.get_character(character_id)
        if not character.can_act:
            raise ValueError("El personaje no puede soltar nada.")
        item = next((one for one in character.inventory if one.id == item_id), None)
        if item is None:
            raise ValueError(f"No llevas ningun '{item_id}'.")
        if enforce_economy and not character.resources.object_interaction:
            raise ValueError("Ya has manipulado un objeto este turno.")
        location = self.location_of(character_id)

        character.inventory.remove(item)
        item.cell = character.position if location.grid is not None else None
        location.items.append(item)
        if enforce_economy:
            character.resources.object_interaction = False
        self.event_bus.publish(Event(
            "ITEM_DROPPED", character_id,
            data={"item_id": item.id, "item_name": item.name, "location_id": location.id},
        ))
        return item

    def unlock_door(self, door_id: str, character_id: str | None = None) -> Door:
        door = self.world.get_door(door_id)
        if not door.locked:
            return door
        if door.key_id is None:
            raise ValueError(f"La puerta '{door_id}' no se abre con ninguna llave.")
        if character_id is not None:
            character = self.get_character(character_id)
            if not any(item.id == door.key_id for item in character.inventory):
                raise ValueError(f"Falta la llave '{door.key_id}' para abrir '{door_id}'.")
        door.locked = False
        self.event_bus.publish(Event(
            "DOOR_UNLOCKED", character_id, data={"door_id": door_id},
        ))
        return door

    def lock_door(self, door_id: str, character_id: str | None = None) -> Door:
        door = self.world.get_door(door_id)
        door.locked = True
        self.event_bus.publish(Event("DOOR_LOCKED", character_id, data={"door_id": door_id}))
        return door

    def distance_between(self, character_id: str, other_id: str) -> int | None:
        """Distancia en pies, o None si no comparten una ubicacion con cuadricula."""
        location = self.world.location_of(character_id)
        other_location = self.world.location_of(other_id)
        if location is None or other_location is None or location.id != other_location.id:
            return None
        if location.grid is None:
            return None
        return distance_in_feet(
            self.get_character(character_id).position, self.get_character(other_id).position,
        )

    def _traverse(self, character: Character, destination: Location, door: Door | None) -> Location:
        cell = door.cell_in(destination.id) if door is not None else None
        self.world.move_character(character.id, destination.id)
        character.position = self._entry_cell(destination, character.id, cell)
        self.event_bus.publish(Event(
            "PLAYER_ENTERED_LOCATION", character.id,
            data={"location_id": destination.id,
                  "door_id": door.id if door is not None else None,
                  "position": list(character.position)},
        ))
        return destination

    def _require_open(self, door: Door) -> None:
        if door.locked:
            raise ValueError(f"La puerta '{door.id}' esta cerrada con llave.")

    def _entry_cell(self, location: Location, character_id: str, preferred: Cell | None) -> Cell:
        """Elige una casilla valida al llegar; sin cuadricula la posicion es irrelevante."""
        character = self.world.characters[character_id]
        if location.grid is None:
            return preferred or character.position
        occupied = self.world.occupied_cells(location.id, ignore=character_id)
        for candidate in (preferred, character.position):
            if candidate is not None and location.grid.is_free(candidate, occupied):
                return candidate
        for candidate in location.grid.free_cells(occupied):
            return candidate
        raise ValueError(f"No queda ninguna casilla libre en '{location.id}'.")
