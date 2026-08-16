"""Best-effort path containment for output roots and run artifacts.

This is defensive filesystem handling, not a security sandbox against a
privileged local attacker. Containment is re-checked immediately before
creating artifacts so a rejected operation leaves zero files outside the
trusted root under the tested symlink/junction swap cases.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .errors import PathEscapeError, ValidationError

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def resolve_canonical(path: str | Path) -> Path:
    """Resolve a path to its canonical form, following symlinks/junctions."""
    return Path(os.path.realpath(str(path)))


def normalize_path_key(path: str | Path) -> str:
    """Normalize for comparison (case-fold on Windows)."""
    text = os.path.normpath(str(path))
    if os.name == "nt":
        text = os.path.normcase(text)
    return text


def validate_contained(target: str | Path, base: str | Path) -> Path:
    """Ensure ``target`` resolves inside ``base``. Return canonical target."""
    base_canonical = resolve_canonical(base)
    target_canonical = resolve_canonical(target)
    try:
        Path(normalize_path_key(target_canonical)).relative_to(
            Path(normalize_path_key(base_canonical))
        )
    except ValueError as exc:
        raise PathEscapeError(
            f"Path '{target}' resolves to '{target_canonical}' which is "
            f"outside the allowed base '{base_canonical}'."
        ) from exc
    return target_canonical


def assert_existing_ancestors_contained(target: str | Path, trusted_root: str | Path) -> None:
    """Validate the deepest existing ancestor of ``target`` stays in root."""
    root = resolve_canonical(trusted_root)
    current = Path(target)
    while True:
        if current.exists():
            validate_contained(current, root)
            break
        if current.parent == current:
            break
        current = current.parent


def safe_id(value: str, *, name: str = "id") -> str:
    """Accept only filesystem-safe identifiers (no separators or ``..``)."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-blank string")
    text = value.strip()
    if ".." in text or "/" in text or "\\" in text or ":" in text:
        raise ValidationError(f"{name} must not contain path separators or '..': {text!r}")
    if not SAFE_ID_RE.match(text):
        raise ValidationError(f"{name} must match {SAFE_ID_RE.pattern} (got {text!r})")
    return text


def safe_join(base: str | Path, *parts: str) -> Path:
    """Join ``parts`` onto ``base`` and require the result stay contained."""
    base_path = Path(base)
    for part in parts:
        safe_id(part, name="path part")
    joined = base_path.joinpath(*parts)
    assert_existing_ancestors_contained(joined, base_path)
    return validate_contained(joined, base_path)
