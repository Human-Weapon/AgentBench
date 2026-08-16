"""Atomic JSON persistence under a configured output root.

Output containment is defensive filesystem handling, not a sandbox against a
privileged local attacker. Corrupt files are quarantined and raise
``CorruptResultError`` — they are never silently treated as an empty success.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import CorruptResultError, PersistenceError, ValidationError
from .models import (
    SCHEMA_VERSION,
    EvaluationResult,
    RunResult,
    RunStatus,
    TargetResult,
    Telemetry,
    WorkspaceDiff,
)
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
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
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
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
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
    return data


class ResultStore:
    """Persists experiment artifacts under ``output_root``."""

    def __init__(self, output_root: str | Path) -> None:
        self.root = Path(output_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        (self.root / "runs").mkdir(exist_ok=True)

    def run_path(self, run_id: str) -> Path:
        ident = safe_id(run_id, name="run_id")
        candidate = self.root / "runs" / f"{ident}.json"
        return validate_contained(candidate, self.root)

    def write_run(self, result: RunResult) -> Path:
        path = self.run_path(result.run_id)
        atomic_write_json(path, result.as_dict(), self.root)
        return path

    def write_json(self, name: str, payload: Mapping[str, Any]) -> Path:
        if name != Path(name).name or ".." in name or "/" in name or "\\" in name:
            raise ValidationError(f"unsafe output name: {name!r}")
        path = validate_contained(self.root / name, self.root)
        atomic_write_json(path, payload, self.root)
        return path

    def write_text(self, name: str, text: str) -> Path:
        if name != Path(name).name or ".." in name:
            raise ValidationError(f"unsafe output name: {name!r}")
        path = validate_contained(self.root / name, self.root)
        assert_existing_ancestors_contained(path, self.root)
        fd, tmp_name = tempfile.mkstemp(prefix=".ab-", suffix=".tmp", dir=str(self.root))
        tmp_path = Path(tmp_name)
        try:
            validate_contained(tmp_path, self.root)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:  # pragma: no cover
                pass
            raise
        return path

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
    tel_raw = target_raw.get("telemetry") or {}
    if not isinstance(tel_raw, Mapping):
        raise CorruptResultError("telemetry must be an object")
    try:
        telemetry = Telemetry(
            **{k: tel_raw.get(k) for k in Telemetry.__dataclass_fields__ if k != "extra"},
            extra=tel_raw.get("extra") or {},
        )
        target = TargetResult(
            status=status,
            stdout=target_raw.get("stdout") or "",
            stderr=target_raw.get("stderr") or "",
            exit_code=target_raw.get("exit_code"),
            duration_seconds=target_raw.get("duration_seconds") or 0.0,
            structured_output=target_raw.get("structured_output"),
            telemetry=telemetry,
            artifacts=target_raw.get("artifacts") or {},
            error_message=target_raw.get("error_message"),
            timed_out=bool(target_raw.get("timed_out")),
            infrastructure_error=bool(target_raw.get("infrastructure_error")),
        )
        evaluations = []
        for item in data.get("evaluations") or []:
            if not isinstance(item, Mapping):
                raise CorruptResultError("evaluation entries must be objects")
            evaluations.append(
                EvaluationResult(
                    evaluator=item["evaluator"],
                    passed=item.get("passed"),
                    score=item.get("score"),
                    details=item.get("details") or {},
                    error=item.get("error"),
                )
            )
        diff = None
        diff_raw = data.get("workspace_diff")
        if diff_raw is not None:
            if not isinstance(diff_raw, Mapping):
                raise CorruptResultError("workspace_diff must be an object")
            diff = WorkspaceDiff(
                files_created=diff_raw.get("files_created") or 0,
                files_modified=diff_raw.get("files_modified") or 0,
                files_deleted=diff_raw.get("files_deleted") or 0,
                bytes_changed=diff_raw.get("bytes_changed") or 0,
                created_paths=tuple(diff_raw.get("created_paths") or ()),
                modified_paths=tuple(diff_raw.get("modified_paths") or ()),
                deleted_paths=tuple(diff_raw.get("deleted_paths") or ()),
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
            started_at=data.get("started_at") or "",
            finished_at=data.get("finished_at") or "",
            schema_version=version,
        )
    except CorruptResultError:
        raise
    except Exception as exc:
        raise CorruptResultError(f"run result failed schema validation: {exc}") from exc
