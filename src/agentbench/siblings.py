"""Optional sibling discovery. Never imports siblings at module load."""

from __future__ import annotations

import importlib.util
from typing import Any

_SIBLINGS = ("promptgraph", "agentgear", "skillguard", "projectkaizen")


def is_installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def load_sibling(name: str) -> Any | None:
    if not is_installed(name):
        return None
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001 - degrade
        return None


def detect_integrations() -> dict[str, bool]:
    return {name: is_installed(name) for name in _SIBLINGS}


def sibling_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in _SIBLINGS:
        mod = load_sibling(name)
        out[name] = getattr(mod, "__version__", "unknown") if mod is not None else None
    return out
