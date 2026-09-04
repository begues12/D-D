"""La cronica ilustrada: una lamina por escena, segun avanza la aventura.

Tres modos, de mas a menos capaz, y siempre hay uno disponible:

1. **Con una IA que dibuja** - se le pide la lamina y se ensena tal cual. Ningun
   proveedor de los que hay ahora mismo lo hace; el hueco esta abierto en
   `providers.py` (`supports_images` / `generate_image`) y el dia que se anada
   uno que dibuje, la columna se llena de imagenes sin tocar nada mas.
2. **Con una IA de texto** - una llamada corta por escena: titulo, pie y un
   emblema de una lista cerrada. La columna dibuja una lamina iluminada con eso.
3. **Sin IA** - la escena sale de lo que ya sabe el motor: donde estas, que hay
   y quien esta. La columna nunca se queda vacia.

Ilustrar cuesta dinero, asi que no se hace cada turno: solo al abrir la aventura
y al pisar una ubicacion nueva. De eso decide `should_illustrate`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ai_dm import ModelSession
from .game import GameEngine

# Los emblemas que la columna sabe dibujar. El modelo elige uno de estos.
EMBLEMS = ("puerta", "llama", "hueso", "agua", "arbol", "espada", "ojo", "moneda",
           "corona", "luna")

# Eventos que merecen lamina. Lo demas -atacar, moverse- llenaria la columna de
# ruido y de facturas.
ILLUSTRATED_EVENTS = ("PLAYER_ENTERED_LOCATION", "QUEST_COMPLETED")

ILLUSTRATOR_SYSTEM = """\
Eres el ilustrador de una cronica de D&D. De cada escena entregas una lamina: \
un titulo corto, un pie de dos frases y un emblema.

El pie describe lo que se ve, no lo que pasa: luz, materiales, olor, que ocupa \
el espacio. Nada de tiradas, nada de reglas, nada que los datos no digan.

Escribe en espanol, sin tildes ni caracteres especiales.
"""

ILLUSTRATE_TOOL = {
    "name": "illustrate",
    "description": "Entrega la lamina de la escena.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Titulo corto, tres o cuatro palabras."},
            "caption": {"type": "string", "description": "Dos frases de lo que se ve."},
            "emblem": {"type": "string", "enum": list(EMBLEMS),
                       "description": "El simbolo que resume la escena."},
        },
        "required": ["title", "caption", "emblem"],
    },
}


@dataclass(frozen=True)
class Illustration:
    """Una lamina de la cronica."""

    title: str
    caption: str
    emblem: str = "luna"
    image: bytes | None = None          # PNG, si la IA sabe dibujar

    @property
    def drawn(self) -> bool:
        return self.image is not None


def scene_of(engine: GameEngine, actor_id: str) -> Illustration:
    """La lamina que se puede hacer sin preguntarle a nadie."""
    location = engine.world.location_of(actor_id)
    if location is None:
        return Illustration("En ninguna parte", "El mundo aun no esta puesto.")
    parts = [location.description or "Un lugar sin describir."]
    present = [engine.world.world.characters[one].name
               for one in sorted(location.occupants) if one != actor_id]
    if present:
        parts.append("Contigo: " + ", ".join(present) + ".")
    if location.items:
        parts.append("A la vista: " + ", ".join(one.name for one in location.items) + ".")
    return Illustration(location.name, " ".join(parts), _emblem_for(location))


def _emblem_for(location: Any) -> str:
    """Un emblema decente a partir del nombre, para cuando no hay IA."""
    text = f"{location.name} {location.description}".lower()
    for emblem, words in (
        ("agua", ("vado", "rio", "pozo", "agua", "pantano", "ahogado")),
        ("hueso", ("cripta", "tumba", "hueso", "sarcofago", "muerto")),
        ("llama", ("forja", "fuego", "horno", "alquimista", "torre")),
        ("moneda", ("taberna", "bodega", "tesoro", "botin", "mercado")),
        ("arbol", ("bosque", "raiz", "jardin", "claro")),
        ("puerta", ("puerta", "porton", "umbral", "vestibulo", "entrada")),
    ):
        if any(word in text for word in words):
            return emblem
    return "luna"


def should_illustrate(events: Any) -> bool:
    """Solo se ilustra lo que cambia de sitio o cierra una mision."""
    return any(getattr(one, "type", None) in ILLUSTRATED_EVENTS for one in events)


class Illustrator(ModelSession):
    """Le pide la lamina a la IA; si algo falla, devuelve la del motor."""

    def illustrate(self, engine: GameEngine, actor_id: str,
                   narration: str = "") -> Illustration:
        fallback = scene_of(engine, actor_id)
        if self.provider.supports_images:
            image = self.provider.generate_image(self.client, self._prompt(
                engine, actor_id, narration))
            if image:
                return Illustration(fallback.title, fallback.caption,
                                    fallback.emblem, image)

        reply = self._call(
            system=self._system(ILLUSTRATOR_SYSTEM),
            tools=[ILLUSTRATE_TOOL],
            tool_choice={"type": "tool", "name": ILLUSTRATE_TOOL["name"]},
            messages=[{"role": "user", "content": self._prompt(engine, actor_id, narration)}],
        )
        blocks = reply.tool_uses(ILLUSTRATE_TOOL["name"])
        if not blocks:
            return fallback
        data = blocks[0].input
        emblem = data.get("emblem")
        return Illustration(
            (data.get("title") or fallback.title).strip(),
            (data.get("caption") or fallback.caption).strip(),
            emblem if emblem in EMBLEMS else fallback.emblem,
        )

    def _prompt(self, engine: GameEngine, actor_id: str, narration: str) -> str:
        location = engine.world.location_of(actor_id)
        lines = [f"Lugar: {location.name}. {location.description}" if location
                 else "Lugar: desconocido."]
        if location is not None:
            present = [engine.world.world.characters[one].name
                       for one in sorted(location.occupants) if one != actor_id]
            if present:
                lines.append("Quien hay: " + ", ".join(present))
            if location.items:
                lines.append("Objetos a la vista: "
                             + ", ".join(one.name for one in location.items))
        if narration:
            lines.append(f"Lo ultimo que se ha contado: {narration}")
        return "\n".join(lines)
