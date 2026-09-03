"""Geometria del mapa: cuadriculas, puertas, distancias y caminos.

Este modulo no conoce personajes ni reglas: solo casillas. Las validaciones de
movimiento viven en `world.py`, que combina esta geometria con el estado del
mundo y la economia de turno.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

Cell = tuple[int, int]

# En 5e cada casilla cuesta 5 pies, tambien en diagonal.
CELL_FEET = 5

_NEIGHBOURS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def distance_in_cells(origin: Cell, destination: Cell) -> int:
    """Distancia de Chebyshev: la diagonal cuenta como una casilla."""
    return max(abs(origin[0] - destination[0]), abs(origin[1] - destination[1]))


def distance_in_feet(origin: Cell, destination: Cell) -> int:
    return distance_in_cells(origin, destination) * CELL_FEET


def are_adjacent(origin: Cell, destination: Cell) -> bool:
    return distance_in_cells(origin, destination) <= 1


@dataclass
class Grid:
    """Cuadricula de una habitacion, con las casillas intransitables."""

    width: int
    height: int
    blocked: set[Cell] = field(default_factory=set)

    def contains(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.width and 0 <= cell[1] < self.height

    def is_free(self, cell: Cell, occupied: frozenset[Cell] | set[Cell] = frozenset()) -> bool:
        return self.contains(cell) and cell not in self.blocked and cell not in occupied

    def free_cells(self, occupied: frozenset[Cell] | set[Cell] = frozenset()):
        for y in range(self.height):
            for x in range(self.width):
                if self.is_free((x, y), occupied):
                    yield (x, y)

    def path(
        self,
        origin: Cell,
        destination: Cell,
        occupied: frozenset[Cell] | set[Cell] = frozenset(),
    ) -> list[Cell] | None:
        """Camino mas corto en casillas, sin incluir el origen.

        Devuelve None si no hay ruta. Como todas las casillas cuestan lo mismo,
        una busqueda en anchura basta y evita heuristicas que enmascaren muros.
        """
        if origin == destination:
            return []
        if not self.is_free(destination, occupied):
            return None
        previous: dict[Cell, Cell] = {origin: origin}
        queue: deque[Cell] = deque([origin])
        while queue:
            current = queue.popleft()
            for offset_x, offset_y in _NEIGHBOURS:
                neighbour = (current[0] + offset_x, current[1] + offset_y)
                if neighbour in previous or not self.is_free(neighbour, occupied):
                    continue
                previous[neighbour] = current
                if neighbour == destination:
                    return _rebuild_path(previous, origin, destination)
                queue.append(neighbour)
        return None


def _rebuild_path(previous: dict[Cell, Cell], origin: Cell, destination: Cell) -> list[Cell]:
    path = [destination]
    while path[-1] != origin:
        path.append(previous[path[-1]])
    path.pop()
    path.reverse()
    return path


@dataclass
class Door:
    """Conexion entre dos ubicaciones. Es la unica forma de pasar de una a otra."""

    id: str
    location_a: str
    location_b: str
    cell_a: Cell | None = None
    cell_b: Cell | None = None
    locked: bool = False
    key_id: str | None = None
    hidden: bool = False

    def connects(self, location_id: str) -> bool:
        return location_id in (self.location_a, self.location_b)

    def other_side(self, location_id: str) -> str:
        if location_id == self.location_a:
            return self.location_b
        if location_id == self.location_b:
            return self.location_a
        raise ValueError(f"La puerta '{self.id}' no da a '{location_id}'.")

    def cell_in(self, location_id: str) -> Cell | None:
        if location_id == self.location_a:
            return self.cell_a
        if location_id == self.location_b:
            return self.cell_b
        raise ValueError(f"La puerta '{self.id}' no da a '{location_id}'.")
