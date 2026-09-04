"""Almacenamiento local de credenciales usando Windows DPAPI.

Una clave por proveedor de IA, cifrada con la cuenta de Windows del usuario:
asi se puede tener la de una casa y la de otra a la vez y cambiar sin volver a
escribirlas. Nunca va al repositorio ni a la partida guardada.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

from .providers import DEFAULT_PROVIDER


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _storage_path(provider: str = DEFAULT_PROVIDER) -> Path:
    root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return root / "DndEngine" / f"{provider}.key"


def _protect(value: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("El almacenamiento seguro de credenciales requiere Windows.")
    source_buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "D&D Engine", None, None, None, 0, ctypes.byref(result)
    ):
        raise OSError(ctypes.get_last_error(), "Windows no pudo cifrar la clave.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def _unprotect(value: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("El almacenamiento seguro de credenciales requiere Windows.")
    source_buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    result = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)
    ):
        raise OSError(ctypes.get_last_error(), "Windows no pudo descifrar la clave.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def save_api_key(api_key: str, provider: str = DEFAULT_PROVIDER) -> None:
    key = api_key.strip()
    if not key:
        raise ValueError("La clave API no puede estar vacia.")
    path = _storage_path(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_protect(key.encode("utf-8")))


def load_api_key(provider: str = DEFAULT_PROVIDER) -> str | None:
    path = _storage_path(provider)
    if not path.exists():
        return None
    return _unprotect(path.read_bytes()).decode("utf-8")


def delete_api_key(provider: str = DEFAULT_PROVIDER) -> None:
    _storage_path(provider).unlink(missing_ok=True)
