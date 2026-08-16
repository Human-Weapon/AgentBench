"""Load suite configuration from JSON (stdlib) or optional YAML."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .evaluators import Evaluator, evaluator_from_config
from .models import (
    BenchmarkCase,
    BenchmarkSuite,
    ExecutionBudget,
    MetricDefinition,
    PricingConfig,
    Variant,
)
from .regression import RegressionPolicy
from .targets import CommandTarget, default_python_argv


def _load_raw(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"cannot read config {file_path}: {exc}") from exc
    suffix = file_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ConfigurationError(
                "YAML config requires optional dependency PyYAML (pip install agentbench[yaml])"
            ) from exc
        try:
            data = yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001
            raise ConfigurationError(f"invalid YAML in {file_path}: {exc}") from exc
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"invalid JSON in {file_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ConfigurationError("config root must be an object")
    return dict(data)


def load_suite(path: str | Path) -> BenchmarkSuite:
    return suite_from_dict(_load_raw(path), base_dir=Path(path).parent)


def suite_from_dict(raw: Mapping[str, Any], *, base_dir: Path | None = None) -> BenchmarkSuite:
    try:
        cases = tuple(
            BenchmarkCase(
                id=item["id"],
                name=item.get("name") or item["id"],
                description=item.get("description") or "",
                payload=item.get("payload"),
                expected=item.get("expected"),
                tags=tuple(item.get("tags") or ()),
                metadata=item.get("metadata") or {},
                timeout_seconds=item.get("timeout_seconds"),
                workspace_template=item.get("workspace_template"),
                validation_command=item.get("validation_command"),
            )
            for item in raw.get("cases") or ()
        )
        variants = tuple(
            Variant(
                id=item["id"],
                name=item.get("name") or item["id"],
                description=item.get("description") or "",
                config=item.get("config") or {},
                tags=tuple(item.get("tags") or ()),
            )
            for item in raw.get("variants") or ()
        )
        budget_raw = raw.get("budget") or {}
        budget = ExecutionBudget(
            max_runs=budget_raw.get("max_runs"),
            per_run_timeout_seconds=budget_raw.get("per_run_timeout_seconds", 60.0),
            max_total_duration_seconds=budget_raw.get("max_total_duration_seconds"),
            max_total_cost=budget_raw.get("max_total_cost"),
            max_failures=budget_raw.get("max_failures"),
        )
        metrics = tuple(
            MetricDefinition(
                name=item["name"],
                direction=item["direction"],
                minimum=item.get("minimum"),
                maximum=item.get("maximum"),
                weight=item.get("weight"),
            )
            for item in raw.get("metrics") or ()
        )
        return BenchmarkSuite(
            id=raw["id"],
            name=raw.get("name") or raw["id"],
            description=raw.get("description") or "",
            cases=cases,
            variants=variants,
            repetitions=raw.get("repetitions", 1),
            seed=raw.get("seed", 0),
            budget=budget,
            metrics=metrics,
            baseline_variant_id=raw.get("baseline") or raw.get("baseline_variant_id"),
            metadata=raw.get("metadata") or {},
            workspace_template=raw.get("workspace_template"),
        )
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"invalid suite configuration: {exc}") from exc


def load_evaluators(raw: Mapping[str, Any]) -> tuple[Evaluator, ...]:
    items = raw.get("evaluators") or ()
    return tuple(evaluator_from_config(item) for item in items)


def load_target(raw: Mapping[str, Any], *, base_dir: Path | None = None) -> Any:
    target = raw.get("target")
    if not isinstance(target, Mapping):
        raise ConfigurationError("config.target is required")
    kind = target.get("type")
    if kind == "command":
        argv = target.get("argv")
        if argv is None and target.get("script"):
            script = str(target["script"])
            if base_dir is not None and not Path(script).is_absolute():
                script = str((base_dir / script).resolve())
            argv = default_python_argv(script)
        return CommandTarget(
            argv,
            cwd=target.get("cwd"),
            env=target.get("env"),
            timeout_seconds=target.get("timeout_seconds"),
        )
    if kind == "python_callable":
        raise ConfigurationError(
            "python_callable targets cannot be loaded from config (no dynamic exec)"
        )
    raise ConfigurationError(f"unknown target type: {kind!r}")


def load_policy(raw: Mapping[str, Any]) -> RegressionPolicy | None:
    block = raw.get("regression")
    if not block:
        return None
    return RegressionPolicy.from_config(block)


def load_pricing(raw: Mapping[str, Any]) -> PricingConfig | None:
    block = raw.get("pricing")
    if not block:
        return None
    return PricingConfig(
        input_token_rate=block.get("input_token_rate"),
        output_token_rate=block.get("output_token_rate"),
    )
