"""Almacenamiento local de credenciales usando Windows DPAPI."""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _storage_path() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return root / "DndEngine" / "anthropic.key"


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


def save_api_key(api_key: str) -> None:
    key = api_key.strip()
    if not key:
        raise ValueError("La clave API no puede estar vacia.")
    path = _storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_protect(key.encode("utf-8")))


def load_api_key() -> str | None:
    path = _storage_path()
    if not path.exists():
        return None
    return _unprotect(path.read_bytes()).decode("utf-8")


def delete_api_key() -> None:
    _storage_path().unlink(missing_ok=True)
