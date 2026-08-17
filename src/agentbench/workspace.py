"""Isolated workspaces and lightweight filesystem diffs.

The template/source directory is never written. Each run receives a copy.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .errors import SourceMutationError, ValidationError
from .models import WorkspaceDiff

DEFAULT_IGNORE = (
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".agentbench-out",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    ".tox",
    ".eggs",
    "*.pyc",
    "*.pyo",
)


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            attrs = os.lstat(path).st_file_attributes  # type: ignore[attr-defined]
            return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except (AttributeError, OSError):
            return False
    return False


def _assert_no_escaping_links(root: Path) -> None:
    root_canon = Path(os.path.realpath(root))
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in list(dirnames) + list(filenames):
            current = Path(dirpath) / name
            if not _is_reparse(current):
                continue
            resolved = Path(os.path.realpath(current))
            try:
                resolved.relative_to(root_canon)
            except ValueError as exc:
                raise ValidationError(
                    f"workspace template contains a link escaping the source tree: {current}"
                ) from exc


class WorkspaceProvider(Protocol):
    def create(self, destination: str | Path) -> Path: ...


def _ignored(rel: str, ignore: Sequence[str]) -> bool:
    parts = Path(rel).parts
    name = Path(rel).name
    for pattern in ignore:
        if pattern.startswith("*"):
            suffix = pattern[1:]
            if name.endswith(suffix):
                return True
            continue
        if pattern in parts or name == pattern:
            return True
    return False


def snapshot_tree(
    root: str | Path, ignore: Sequence[str] = DEFAULT_IGNORE
) -> dict[str, tuple[str, int]]:
    """Map relative posix paths to ``(sha256, size)``."""
    base = Path(root)
    if not base.is_dir():
        raise ValidationError(f"snapshot root is not a directory: {base}")
    out: dict[str, tuple[str, int]] = {}
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base)
        dirnames[:] = [
            d
            for d in dirnames
            if not _ignored(
                str(Path(rel_dir, d).as_posix() if rel_dir != "." else d),
                ignore,
            )
        ]
        for filename in filenames:
            full = Path(dirpath) / filename
            rel = full.relative_to(base).as_posix()
            if _ignored(rel, ignore):
                continue
            data = full.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            out[rel] = (digest, len(data))
    return out


def source_fingerprint(root: str | Path, ignore: Sequence[str] = DEFAULT_IGNORE) -> str:
    snap = snapshot_tree(root, ignore)
    hasher = hashlib.sha256()
    for path in sorted(snap):
        digest, size = snap[path]
        hasher.update(path.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(digest.encode("ascii"))
        hasher.update(b"\0")
        hasher.update(str(size).encode("ascii"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def diff_snapshots(
    before: dict[str, tuple[str, int]],
    after: dict[str, tuple[str, int]],
) -> WorkspaceDiff:
    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(p for p in set(before) & set(after) if before[p][0] != after[p][0])
    bytes_changed = 0
    for path in created:
        bytes_changed += after[path][1]
    for path in deleted:
        bytes_changed += before[path][1]
    for path in modified:
        bytes_changed += abs(after[path][1] - before[path][1])
    return WorkspaceDiff(
        files_created=len(created),
        files_modified=len(modified),
        files_deleted=len(deleted),
        bytes_changed=bytes_changed,
        created_paths=tuple(created),
        modified_paths=tuple(modified),
        deleted_paths=tuple(deleted),
    )


class DirectoryCopyWorkspace:
    """Copy a template directory into a per-run destination."""

    def __init__(
        self,
        template: str | Path,
        *,
        ignore: Sequence[str] = DEFAULT_IGNORE,
    ) -> None:
        self.template = Path(template)
        if not self.template.is_dir():
            raise ValidationError(f"workspace template is not a directory: {self.template}")
        _assert_no_escaping_links(self.template)
        self.ignore = tuple(ignore)
        self._source_hash = source_fingerprint(self.template, self.ignore)

    @property
    def source_hash(self) -> str:
        return self._source_hash

    def assert_source_unchanged(self) -> None:
        current = source_fingerprint(self.template, self.ignore)
        if current != self._source_hash:
            raise SourceMutationError(f"workspace template was mutated: {self.template}")

    def create(self, destination: str | Path) -> Path:
        dest = Path(destination)
        if dest.exists():
            raise ValidationError(f"workspace destination already exists: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)

        def _ignore(directory: str, names: list[str]) -> set[str]:
            skipped: set[str] = set()
            rel_dir = os.path.relpath(directory, self.template)
            for name in names:
                rel = Path(rel_dir, name).as_posix() if rel_dir != "." else name
                if _ignored(rel, self.ignore):
                    skipped.add(name)
            return skipped

        shutil.copytree(self.template, dest, ignore=_ignore, symlinks=True)
        self.assert_source_unchanged()
        return dest


def write_case_files(workspace: Path, case_payload: object, variant_config: object) -> None:
    """Drop case/variant JSON into the isolated workspace (not the template)."""
    import json

    from .jsonutil import to_jsonable

    (workspace / "case.json").write_text(
        json.dumps(to_jsonable(case_payload, name="case_payload"), indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (workspace / "variant.json").write_text(
        json.dumps(to_jsonable(variant_config, name="variant_config"), indent=2, allow_nan=False),
        encoding="utf-8",
    )
