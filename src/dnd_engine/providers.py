"""Que IA hay detras. Hoy Anthropic; manana la que sea.

El motor no habla con ningun SDK: habla con un `Provider`, que es lo unico que
sabe de credenciales, modelos, formato de peticion y errores de una casa
concreta. Todo lo demas -el DM, la fragua, el asistente- trabaja con dos cosas
neutras: una peticion con `system`, `messages` y `tools`, y una `Reply` con
bloques de texto y de uso de herramienta.

Anadir otra IA es escribir una subclase y meterla en `PROVIDERS`. Lo que hay
que cubrir, y nada mas:

    id / name / env_var / default_model / package     como se llama y con que
    create_client()                                   abrir el cliente
    create_message(...)                               mandar la peticion
    supports_images / generate_image(...)             dibujar, si sabe
    normalize(...)                                    traer la respuesta a `Reply`
    assistant_echo(...)                               devolverle lo que dijo
    translate(error)                                  sus errores, en cristiano

El resto del programa no distingue una casa de otra. La clave se guarda por
proveedor (`credentials.py`), asi que se puede tener una de cada y cambiar sin
volver a escribirlas.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# La API se sobrecarga y perder un turno por eso es inaceptable, asi que se
# reintenta mas que el valor por defecto de los SDK.
DEFAULT_RETRIES = 5
OVERLOADED_STATUS = frozenset({429, 500, 502, 503, 504, 529})

# Con que proveedor se arranca si nadie dice otra cosa.
PROVIDER_ENV = "DND_AI_PROVIDER"
DEFAULT_PROVIDER = "anthropic"


# -- lo que va y viene, sin casa -----------------------------------------------


@dataclass(frozen=True)
class TextBlock:
    text: str
    type: str = "text"


@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)
    type: str = "tool_use"


@dataclass(frozen=True)
class Reply:
    """Una respuesta del modelo, ya neutra."""

    content: tuple[Any, ...] = ()
    stop_reason: str | None = None
    raw: Any = None                      # la respuesta original, para reenviarla

    @property
    def text(self) -> str:
        return "".join(one.text for one in self.content
                       if getattr(one, "type", None) == "text").strip()

    def tool_uses(self, name: str | None = None) -> list[ToolUseBlock]:
        return [one for one in self.content
                if getattr(one, "type", None) == "tool_use"
                and (name is None or one.name == name)]


class ProviderError(RuntimeError):
    """No se pudo ni abrir el cliente: falta el SDK o la credencial."""


# -- el contrato ---------------------------------------------------------------


class Provider:
    id = ""
    name = ""
    env_var = ""
    default_model = ""
    package = ""             # el modulo que hay que instalar
    extra = "ai"             # el extra de pip que lo trae

    # -- credenciales ---------------------------------------------------

    @property
    def install_hint(self) -> str:
        return f'Falta el SDK de {self.name}: pip install "dnd-engine[{self.extra}]"'

    @property
    def missing_key_hint(self) -> str:
        return f"No hay credencial de {self.name}: define {self.env_var}."

    def api_key(self) -> str | None:
        return os.environ.get(self.env_var) or None

    def use_key(self, api_key: str) -> None:
        """Deja la clave donde el SDK la va a encontrar."""
        os.environ[self.env_var] = api_key.strip()

    def forget_key(self) -> None:
        os.environ.pop(self.env_var, None)

    def is_configured(self) -> bool:
        return bool(self.api_key())

    # -- transporte -----------------------------------------------------

    def module(self) -> Any | None:
        try:
            return __import__(self.package)
        except ImportError:
            return None

    def create_client(self, retries: int = DEFAULT_RETRIES) -> Any:
        raise NotImplementedError

    def create_message(self, client: Any, **request: Any) -> Reply:
        raise NotImplementedError

    # -- laminas ---------------------------------------------------------
    # La cronica ilustrada pinta imagenes si la casa sabe hacerlas. Ninguna de
    # las que hay ahora mismo lo hace, asi que se dibujan laminas iluminadas con
    # el titulo y el emblema que da el modelo. Una casa que dibuje solo tiene que
    # poner `supports_images = True` y devolver el PNG.

    supports_images = False

    def generate_image(self, client: Any, prompt: str) -> bytes | None:
        return None

    def assistant_echo(self, reply: Reply) -> Any:
        """Lo que se le devuelve al modelo cuando hay que continuar la conversacion."""
        raise NotImplementedError

    def translate(self, error: Exception) -> tuple[str, bool] | None:
        """(mensaje, se puede reintentar), o None si el error no es suyo."""
        return None

    def __str__(self) -> str:
        return self.name


class AnthropicProvider(Provider):
    id = "anthropic"
    name = "Anthropic"
    env_var = "ANTHROPIC_API_KEY"
    default_model = "claude-opus-5"
    package = "anthropic"

    def create_client(self, retries: int = DEFAULT_RETRIES) -> Any:
        anthropic = self.module()
        if anthropic is None:
            raise ProviderError(self.install_hint)
        try:
            return anthropic.Anthropic(max_retries=retries)
        except TypeError as error:
            # Sin credencial el SDK ni siquiera llega a construirse.
            raise ProviderError(
                f"{self.missing_key_hint} O ejecuta 'ant auth login'.") from error

    def create_message(self, client: Any, *, model: str, max_tokens: int,
                       effort: str, system: Any, messages: list[dict[str, Any]],
                       tools: Any = None, tool_choice: Any = None) -> Reply:
        optional: dict[str, Any] = {}
        if tools is not None:
            optional["tools"] = tools
        if tool_choice is not None:
            optional["tool_choice"] = tool_choice
        response = client.messages.create(
            model=model, max_tokens=max_tokens, output_config={"effort": effort},
            system=system, messages=messages, **optional,
        )
        return self.normalize(response)

    def normalize(self, response: Any) -> Reply:
        blocks = []
        for block in getattr(response, "content", []) or []:
            kind = getattr(block, "type", None)
            if kind == "text":
                blocks.append(TextBlock(block.text))
            elif kind == "tool_use":
                blocks.append(ToolUseBlock(getattr(block, "id", ""), block.name,
                                           dict(block.input or {})))
        return Reply(tuple(blocks), getattr(response, "stop_reason", None), response)

    def assistant_echo(self, reply: Reply) -> Any:
        # Los bloques originales del SDK valen tal cual como turno del asistente.
        return reply.raw.content

    def translate(self, error: Exception) -> tuple[str, bool] | None:
        if isinstance(error, ProviderError):
            return str(error), False
        if isinstance(error, TypeError) and "authentication" in str(error).lower():
            return f"{self.missing_key_hint} O ejecuta 'ant auth login'.", False
        anthropic = self.module()
        if anthropic is None:
            return None
        if isinstance(error, anthropic.AuthenticationError):
            return f"Credencial de {self.name} invalida o ausente: define {self.env_var}.", False
        if isinstance(error, anthropic.NotFoundError):
            return "El modelo pedido no existe en esta cuenta.", False
        if isinstance(error, anthropic.APIStatusError):
            if error.status_code in OVERLOADED_STATUS:
                return (f"La API esta sobrecargada ({error.status_code}) y no ha cedido "
                        "tras varios reintentos."), True
            return f"La API respondio {error.status_code}: {error.message}", False
        if isinstance(error, anthropic.APIConnectionError):
            return f"No se pudo conectar con la API de {self.name}.", True
        return None


PROVIDERS: dict[str, Provider] = {one.id: one for one in (AnthropicProvider(),)}


def get_provider(identifier: str | Provider | None = None) -> Provider:
    """El proveedor pedido, el de la variable de entorno, o el de por defecto."""
    if isinstance(identifier, Provider):
        return identifier
    name = (identifier or os.environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).lower()
    if name not in PROVIDERS:
        raise ValueError(
            f"No conozco la IA '{name}'. Opciones: {', '.join(sorted(PROVIDERS))}.")
    return PROVIDERS[name]
