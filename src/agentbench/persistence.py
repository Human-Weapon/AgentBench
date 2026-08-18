"""Atomic JSON persistence under a configured output root.

Output containment is defensive filesystem handling, not a sandbox against a
privileged local attacker. Corrupt files are quarantined and raise
``CorruptResultError`` — they are never silently treated as an empty success.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import (
    ConfigurationError,
    CorruptResultError,
    PathEscapeError,
    PersistenceError,
    ValidationError,
)
from .jsonutil import to_jsonable
from .models import (
    SCHEMA_VERSION,
    EvaluationResult,
    RunResult,
    RunStatus,
    TargetResult,
    Telemetry,
    WorkspaceDiff,
)
from .numbers import reject_json_constant, reject_nonfinite_tree, require_bool
from .paths import assert_existing_ancestors_contained, safe_id, validate_contained


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: Mapping[str, Any], trusted_root: Path) -> None:
    """Write JSON via a unique temp file + ``os.replace`` inside ``trusted_root``."""
    trusted = Path(trusted_root)
    path = Path(path)
    assert_existing_ancestors_contained(path, trusted)
    path.parent.mkdir(parents=True, exist_ok=True)
    validate_contained(path.parent, trusted)
    fd, tmp_name = tempfile.mkstemp(prefix=".ab-", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        validate_contained(tmp_path, trusted)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                to_jsonable(dict(payload), name="persist"),
                handle,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        validate_contained(path, trusted)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:  # pragma: no cover
            pass
        raise


def _quarantine(path: Path) -> str | None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = path.with_name(path.name + f".corrupt-{stamp}")
    try:
        path.replace(dest)
        return str(dest)
    except OSError:
        return None


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PersistenceError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(raw, parse_constant=reject_json_constant)
    except json.JSONDecodeError as exc:
        quarantined = _quarantine(path)
        raise CorruptResultError(
            f"invalid JSON in {path}: {exc}",
            quarantined_path=quarantined,
        ) from exc
    except ValidationError as exc:
        quarantined = _quarantine(path)
        raise CorruptResultError(
            f"invalid JSON in {path}: {exc}",
            quarantined_path=quarantined,
        ) from exc
    if not isinstance(data, dict):
        quarantined = _quarantine(path)
        raise CorruptResultError(
            f"result root must be an object, got {type(data).__name__}",
            quarantined_path=quarantined,
        )
    try:
        reject_nonfinite_tree(data, name="result")
    except Exception as exc:
        quarantined = _quarantine(path)
        raise CorruptResultError(
            f"non-finite number in {path}: {exc}",
            quarantined_path=quarantined,
        ) from exc
    return data


_OUTPUT_MARKERS = ("experiment.json", "summary.json", "comparison.json", "report.md")


def assert_unused_output(output_root: str | Path) -> None:
    """Refuse to start an experiment in a directory that already has results."""
    root = Path(output_root)
    if not root.exists():
        return
    for name in _OUTPUT_MARKERS:
        if (root / name).exists():
            raise ConfigurationError(
                f"output directory already contains {name}; refusing to mix experiments"
            )
    runs = root / "runs"
    if runs.is_dir() and any(runs.glob("*.json")):
        raise ConfigurationError(
            "output directory already contains run results; refusing to mix experiments"
        )


class ResultStore:
    """Persists experiment artifacts under ``output_root``."""

    def __init__(self, output_root: str | Path) -> None:
        self.root = Path(output_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self._identity = os.path.realpath(self.root)
        self._assert_identity()
        (self.root / "runs").mkdir(exist_ok=True)

    def _assert_identity(self) -> None:
        current = os.path.realpath(self.root)
        left = os.path.normcase(current)
        right = os.path.normcase(self._identity)
        if left != right:
            raise PathEscapeError(
                f"output root identity changed: expected {self._identity}, now {current}"
            )

    def run_path(self, run_id: str) -> Path:
        ident = safe_id(run_id, name="run_id")
        candidate = self.root / "runs" / f"{ident}.json"
        return validate_contained(candidate, self.root)

    def write_run(self, result: RunResult) -> Path:
        self._assert_identity()
        path = self.run_path(result.run_id)
        atomic_write_json(path, result.as_dict(), Path(self._identity))
        return path

    def write_json(self, name: str, payload: Mapping[str, Any]) -> Path:
        self._assert_identity()
        if name != Path(name).name or ".." in name or "/" in name or "\\" in name:
            raise ValidationError(f"unsafe output name: {name!r}")
        path = validate_contained(self.root / name, Path(self._identity))
        atomic_write_json(path, payload, Path(self._identity))
        return path

    def write_text(self, name: str, text: str) -> Path:
        self._assert_identity()
        trusted = Path(self._identity)
        if name != Path(name).name or ".." in name or "/" in name or "\\" in name:
            raise ValidationError(f"unsafe output name: {name!r}")
        dest = self.root / name
        if dest.exists() or dest.is_symlink():
            validate_contained(dest, trusted)
        else:
            assert_existing_ancestors_contained(dest, trusted)
        fd, tmp_name = tempfile.mkstemp(prefix=".ab-", suffix=".tmp", dir=str(trusted))
        tmp_path = Path(tmp_name)
        try:
            validate_contained(tmp_path, trusted)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            self._assert_identity()
            if dest.exists() or dest.is_symlink():
                validate_contained(dest, trusted)
            os.replace(tmp_path, dest)
            validate_contained(dest, trusted)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:  # pragma: no cover
                pass
            raise
        return dest

    def contained_filename(self, dest: str | Path | None, *, default: str) -> str:
        """Return a single safe filename that will stay under this store."""
        self._assert_identity()
        if dest is None:
            return default
        path = Path(dest)
        if not path.is_absolute():
            if path.parent != Path(".") and str(path.parent) not in {"", "."}:
                raise ValidationError("output name must be a filename under the results root")
            return path.name
        parent = os.path.realpath(path.parent)
        if os.path.normcase(parent) != os.path.normcase(self._identity):
            raise PathEscapeError("output path is outside the results root")
        return path.name

    def load_run(self, run_id: str) -> RunResult:
        return run_result_from_dict(load_json_object(self.run_path(run_id)))

    def iter_runs(self) -> list[RunResult]:
        results: list[RunResult] = []
        runs_dir = self.root / "runs"
        if not runs_dir.is_dir():
            return results
        for path in sorted(runs_dir.glob("*.json")):
            results.append(run_result_from_dict(load_json_object(path)))
        return results


def _field_mapping(
    raw: Mapping[str, Any], key: str, *, missing_ok: bool = True
) -> Mapping[str, Any]:
    if key not in raw:
        if missing_ok:
            return {}
        raise CorruptResultError(f"{key} is required")
    value = raw[key]
    if value is None:
        raise CorruptResultError(f"{key} must not be null")
    if not isinstance(value, Mapping):
        raise CorruptResultError(f"{key} must be an object")
    return value


def _field_str(raw: Mapping[str, Any], key: str, *, default: str | None = "") -> str | None:
    if key not in raw:
        return default
    value = raw[key]
    if value is None:
        raise CorruptResultError(f"{key} must not be null")
    if not isinstance(value, str):
        raise CorruptResultError(f"{key} must be a string")
    return value


def _nullable_str(raw: Mapping[str, Any], key: str) -> str | None:
    if key not in raw or raw[key] is None:
        return None
    value = raw[key]
    if not isinstance(value, str):
        raise CorruptResultError(f"{key} must be a string or null")
    return value


def _optional_str_tuple(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    if key not in raw:
        return ()
    value = raw[key]
    if value is None:
        raise CorruptResultError(f"{key} must not be null")
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise CorruptResultError(f"{key} must be an array of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise CorruptResultError(f"{key} entries must be strings")
        out.append(item)
    return tuple(out)


def run_result_from_dict(data: Mapping[str, Any]) -> RunResult:
    """Validate persisted schema. Corrupt / incomplete records raise."""
    required = ("schema_version", "run_id", "case_id", "variant_id", "repetition", "seed", "target")
    missing = [key for key in required if key not in data]
    if missing:
        raise CorruptResultError(f"run result missing fields: {missing}")
    version = data["schema_version"]
    if version != SCHEMA_VERSION:
        raise CorruptResultError(f"unsupported schema_version: {version!r}")
    target_raw = data["target"]
    if not isinstance(target_raw, Mapping):
        raise CorruptResultError("target must be an object")
    try:
        status = RunStatus(target_raw["status"])
    except Exception as exc:
        raise CorruptResultError(f"invalid target status: {target_raw.get('status')!r}") from exc
    tel_raw = _field_mapping(target_raw, "telemetry")
    extra = _field_mapping(tel_raw, "extra")
    artifacts = _field_mapping(target_raw, "artifacts")
    try:
        telemetry = Telemetry(
            **{k: tel_raw.get(k) for k in Telemetry.__dataclass_fields__ if k != "extra"},
            extra=extra,
        )
        target = TargetResult(
            status=status,
            stdout=_field_str(target_raw, "stdout", default=""),
            stderr=_field_str(target_raw, "stderr", default=""),
            exit_code=target_raw.get("exit_code"),
            duration_seconds=target_raw.get("duration_seconds", 0.0),
            structured_output=target_raw.get("structured_output"),
            telemetry=telemetry,
            artifacts=artifacts,
            error_message=_nullable_str(target_raw, "error_message"),
            timed_out=require_bool(target_raw.get("timed_out", False), name="timed_out"),
            infrastructure_error=require_bool(
                target_raw.get("infrastructure_error", False), name="infrastructure_error"
            ),
        )
        evaluations = []
        if "evaluations" not in data:
            evals_raw: list[Any] = []
        elif data["evaluations"] is None:
            raise CorruptResultError("evaluations must not be null")
        else:
            evals_raw = data["evaluations"]
        if not isinstance(evals_raw, list):
            raise CorruptResultError("evaluations must be an array")
        for item in evals_raw:
            if not isinstance(item, Mapping):
                raise CorruptResultError("evaluation entries must be objects")
            evaluations.append(
                EvaluationResult(
                    evaluator=item["evaluator"],
                    passed=item.get("passed"),
                    score=item.get("score"),
                    details=_field_mapping(item, "details"),
                    error=_nullable_str(item, "error"),
                )
            )
        diff = None
        diff_raw = data.get("workspace_diff")
        if diff_raw is not None:
            if not isinstance(diff_raw, Mapping):
                raise CorruptResultError("workspace_diff must be an object")
            diff = WorkspaceDiff(
                files_created=diff_raw["files_created"] if "files_created" in diff_raw else 0,
                files_modified=diff_raw["files_modified"] if "files_modified" in diff_raw else 0,
                files_deleted=diff_raw["files_deleted"] if "files_deleted" in diff_raw else 0,
                bytes_changed=diff_raw["bytes_changed"] if "bytes_changed" in diff_raw else 0,
                created_paths=_optional_str_tuple(diff_raw, "created_paths"),
                modified_paths=_optional_str_tuple(diff_raw, "modified_paths"),
                deleted_paths=_optional_str_tuple(diff_raw, "deleted_paths"),
            )
        return RunResult(
            run_id=data["run_id"],
            case_id=data["case_id"],
            variant_id=data["variant_id"],
            repetition=data["repetition"],
            seed=data["seed"],
            target=target,
            evaluations=tuple(evaluations),
            workspace_diff=diff,
            started_at=_field_str(data, "started_at", default=""),
            finished_at=_field_str(data, "finished_at", default=""),
            schema_version=version,
        )
    except CorruptResultError:
        raise
    except Exception as exc:
        raise CorruptResultError(f"run result failed schema validation: {exc}") from exc
