from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentbench.config import load_suite, suite_from_dict
from agentbench.errors import ConfigurationError
from agentbench.models import MetricDirection


def test_load_json_suite(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(
        json.dumps(
            {
                "id": "s",
                "cases": [{"id": "c", "name": "c"}],
                "variants": [{"id": "v", "name": "v"}],
                "repetitions": 2,
                "seed": 3,
            }
        ),
        encoding="utf-8",
    )
    suite = load_suite(path)
    assert suite.repetitions == 2
    assert suite.seed == 3


def test_malformed_suite(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_suite(path)


def test_yaml_optional(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text("id: s\ncases: []\nvariants: []\n", encoding="utf-8")
    try:
        import yaml  # noqa: F401
    except ImportError:
        with pytest.raises(ConfigurationError, match="YAML"):
            load_suite(path)
    else:
        with pytest.raises(ConfigurationError):
            load_suite(path)


def test_metric_direction_from_config() -> None:
    suite = suite_from_dict(
        {
            "id": "s",
            "cases": [{"id": "c", "name": "c"}],
            "variants": [{"id": "v", "name": "v"}],
            "metrics": [{"name": "cost", "direction": "LOWER_IS_BETTER"}],
        }
    )
    assert suite.metrics[0].direction is MetricDirection.LOWER_IS_BETTER
