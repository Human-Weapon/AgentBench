from __future__ import annotations

from agentbench.adapters import AgentGearEvidenceAdapter
from agentbench.fingerprint import collect_fingerprint
from agentbench.siblings import detect_integrations, is_installed


def test_adapter_unknown_keys_stay_extra() -> None:
    tel = AgentGearEvidenceAdapter().to_telemetry(
        {"stall_count": 3, "average_cost": 0.4, "task_class": "refactor"}
    )
    assert tel.stall_count == 3
    assert tel.cost == 0.4
    assert tel.extra["task_class"] == "refactor"
    assert tel.input_tokens is None


def test_fingerprint_survives_missing_git(tmp_path) -> None:
    fp = collect_fingerprint(seed=1, cwd=str(tmp_path))
    assert fp.agentbench_version
    assert fp.python_version
    assert fp.seed == 1
    # git_sha may be None if tmp_path is not a repo — that must not raise.
    assert fp.git_sha is None or isinstance(fp.git_sha, str)


def test_detect_integrations_keys() -> None:
    flags = detect_integrations()
    assert set(flags) == {"promptgraph", "agentgear", "skillguard", "projectkaizen"}
    assert is_installed("definitely_not_a_real_package_xyz") is False
