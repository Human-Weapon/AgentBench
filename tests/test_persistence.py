from __future__ import annotations

from pathlib import Path

import pytest

from agentbench.errors import CorruptResultError, PathEscapeError, ValidationError
from agentbench.models import RunResult, RunStatus, TargetResult
from agentbench.paths import safe_id, safe_join
from agentbench.persistence import ResultStore, load_json_object, run_result_from_dict


def _run(run_id: str = "suite__c__v__r0__s1") -> RunResult:
    return RunResult(
        run_id=run_id,
        case_id="c",
        variant_id="v",
        repetition=0,
        seed=1,
        target=TargetResult(status=RunStatus.SUCCESS, exit_code=0),
    )


def test_atomic_persist_and_reload(tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "out")
    store.write_run(_run())
    loaded = store.load_run("suite__c__v__r0__s1")
    assert loaded.target.status is RunStatus.SUCCESS
    assert (tmp_path / "out" / "runs" / "suite__c__v__r0__s1.json").is_file()


def test_corrupt_json_is_quarantined(tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "out")
    store.write_run(_run())
    path = store.run_path("suite__c__v__r0__s1")
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CorruptResultError) as exc:
        store.load_run("suite__c__v__r0__s1")
    assert exc.value.quarantined_path is not None
    assert Path(exc.value.quarantined_path).exists()
    assert not path.exists()


def test_schema_invalid_object_rejected(tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "out")
    path = store.root / "runs" / "bad.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(CorruptResultError):
        load_json_object(path)
    with pytest.raises(CorruptResultError):
        run_result_from_dict({"schema_version": 1})


def test_path_traversal_id_rejected(tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "out")
    with pytest.raises(ValidationError):
        store.run_path("../escape")
    with pytest.raises(ValidationError):
        safe_id("..\\windows")
    with pytest.raises(ValidationError):
        store.write_json("../outside.json", {"a": 1})


def test_absolute_unsafe_id_rejected() -> None:
    with pytest.raises(ValidationError):
        safe_id("C:/Windows/Temp/x")
    with pytest.raises(ValidationError):
        safe_id("/etc/passwd")


def test_safe_join_stays_in_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    inside = safe_join(root, "runs")
    assert inside == (root / "runs").resolve() or str(inside).endswith("runs")
    with pytest.raises((ValidationError, PathEscapeError)):
        safe_join(root, "..")
