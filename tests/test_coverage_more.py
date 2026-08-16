from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from agentbench.errors import ValidationError
from agentbench.fingerprint import collect_fingerprint
from agentbench.metrics import composite_score, normalize
from agentbench.models import (
    BenchmarkCase,
    BenchmarkSuite,
    MetricDefinition,
    MetricDirection,
    MetricValue,
    MissingMetricBehavior,
    Variant,
)
from agentbench.numbers import require_nonblank_str, require_number
from agentbench.siblings import is_installed, load_sibling
from agentbench.workspace import DirectoryCopyWorkspace, snapshot_tree


def test_require_number_negative_and_blank() -> None:
    with pytest.raises(ValidationError):
        require_number(-1.0, name="cost")
    with pytest.raises(ValidationError):
        require_nonblank_str(12, name="id")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        require_nonblank_str("   ", name="id")


def test_none_tags_and_metadata() -> None:
    case = BenchmarkCase(id="c", name="C", tags=None, metadata=None)
    assert case.tags == ()
    assert case.metadata == {}


def test_metric_value_and_zero_range() -> None:
    MetricValue(name="x", value=1.0, unit="s", source="measured")
    with pytest.raises(ValidationError):
        MetricValue(name="x", value=1.0, unit=1)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        MetricValue(name="x", value=1.0, source=1)  # type: ignore[arg-type]
    bad = MetricDefinition(
        name="z",
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=1,
        maximum=1,
        weight=1,
    )
    with pytest.raises(ValidationError):
        normalize(1, bad)
    with pytest.raises(ValidationError):
        composite_score({"z": 1}, (bad,))


def test_fingerprint_git_failures(tmp_path: Path) -> None:
    with patch("agentbench.fingerprint.subprocess.run", side_effect=OSError("no git")):
        fp = collect_fingerprint(seed=1, cwd=str(tmp_path))
        assert fp.git_sha is None
    with patch(
        "agentbench.fingerprint.subprocess.run",
        return_value=type("R", (), {"returncode": 1, "stdout": ""})(),
    ):
        fp = collect_fingerprint(seed=1, cwd=str(tmp_path))
        assert fp.git_sha is None


def test_sibling_error_paths() -> None:
    with patch("agentbench.siblings.importlib.util.find_spec", side_effect=ValueError("x")):
        assert is_installed("promptgraph") is False
    with patch("agentbench.siblings.is_installed", return_value=True):
        with patch("agentbench.siblings.importlib.import_module", side_effect=RuntimeError("boom")):
            assert load_sibling("promptgraph") is None


def test_workspace_errors(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        snapshot_tree(tmp_path / "missing")
    template = tmp_path / "t"
    template.mkdir()
    (template / "a.txt").write_text("a", encoding="utf-8")
    dest = tmp_path / "d"
    dest.mkdir()
    provider = DirectoryCopyWorkspace(template)
    with pytest.raises(ValidationError):
        provider.create(dest)
    with pytest.raises(ValidationError):
        DirectoryCopyWorkspace(tmp_path / "nope")


def test_suite_unknown_ids() -> None:
    suite = BenchmarkSuite(
        id="s",
        name="S",
        cases=(BenchmarkCase(id="c", name="C"),),
        variants=(Variant(id="v", name="V"),),
    )
    with pytest.raises(ValidationError):
        suite.case_by_id("nope")
    with pytest.raises(ValidationError):
        suite.variant_by_id("nope")


def test_composite_skip_and_empty_weight() -> None:
    definition = MetricDefinition(
        name="only",
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
        weight=1,
    )
    assert (
        composite_score({"only": None}, (definition,), missing=MissingMetricBehavior.SKIP) is None
    )
    missing_weight = MetricDefinition(
        name="w",
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    )
    with pytest.raises(ValidationError):
        composite_score({"w": 1.0}, (missing_weight,))


def test_fingerprint_empty_sha(tmp_path: Path) -> None:
    with patch(
        "agentbench.fingerprint.subprocess.run",
        return_value=type("R", (), {"returncode": 0, "stdout": "  "})(),
    ):
        fp = collect_fingerprint(seed=1, cwd=str(tmp_path))
        assert fp.git_sha is None


def test_stderr_evaluators() -> None:
    from agentbench.evaluators import ContainsTextEvaluator, ExactTextEvaluator, RegexEvaluator
    from agentbench.models import RunStatus, TargetResult

    ctx = {
        "target": TargetResult(status=RunStatus.SUCCESS, stdout="", stderr="err-text", exit_code=0)
    }
    assert ExactTextEvaluator("err-text", source="stderr").evaluate(ctx).passed is True
    assert ContainsTextEvaluator("err", source="stderr").evaluate(ctx).passed is True
    assert RegexEvaluator("err-.+", source="stderr").evaluate(ctx).passed is True


def test_yaml_and_non_object_config(tmp_path: Path) -> None:
    from agentbench.config import _load_raw
    from agentbench.errors import ConfigurationError

    yaml_path = tmp_path / "s.yaml"
    yaml_path.write_text("[]\n", encoding="utf-8")
    try:
        import yaml  # noqa: F401
    except ImportError:
        with pytest.raises(ConfigurationError):
            _load_raw(yaml_path)
    else:
        with pytest.raises(ConfigurationError):
            _load_raw(yaml_path)
    bad = tmp_path / "s.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        _load_raw(bad)
