"""Load suite configuration from JSON (stdlib) or optional YAML."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, ValidationError
from .evaluators import Evaluator, evaluator_from_config
from .models import (
    BenchmarkCase,
    BenchmarkSuite,
    ExecutionBudget,
    MetricDefinition,
    PricingConfig,
    Variant,
)
from .numbers import reject_json_constant, reject_nonfinite_tree
from .regression import RegressionPolicy
from .targets import CommandTarget, default_python_argv

_FILE_KEYS = {
    "schema_version",
    "id",
    "name",
    "description",
    "seed",
    "repetitions",
    "baseline",
    "baseline_variant_id",
    "workspace_template",
    "budget",
    "cases",
    "variants",
    "metrics",
    "target",
    "evaluators",
    "regression",
    "pricing",
    "metadata",
}
_CASE_KEYS = {
    "id",
    "name",
    "description",
    "payload",
    "expected",
    "tags",
    "metadata",
    "timeout_seconds",
    "workspace_template",
    "validation_command",
}
_VARIANT_KEYS = {"id", "name", "description", "config", "tags"}
_BUDGET_KEYS = {
    "max_runs",
    "per_run_timeout_seconds",
    "max_total_duration_seconds",
    "max_total_cost",
    "max_failures",
    "per_run_max_cost",
}


def _unknown(raw: Mapping[str, Any], allowed: set[str], where: str) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ConfigurationError(f"unknown {where} field(s): {extra}")


def _resolve_path(value: str | None, base_dir: Path | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError("path values must be strings")
    path = Path(value)
    if path.is_absolute() or base_dir is None:
        return value
    return str((base_dir / path).resolve())


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
            data = json.loads(text, parse_constant=reject_json_constant)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(f"invalid JSON in {file_path}: {exc}") from exc
        except ValidationError as exc:
            raise ConfigurationError(f"invalid JSON in {file_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ConfigurationError("config root must be an object")
    try:
        reject_nonfinite_tree(data, name="config")
    except ValidationError as exc:
        raise ConfigurationError(str(exc)) from exc
    return dict(data)


def load_suite(path: str | Path) -> BenchmarkSuite:
    return suite_from_dict(_load_raw(path), base_dir=Path(path).parent)


def suite_from_dict(raw: Mapping[str, Any], *, base_dir: Path | None = None) -> BenchmarkSuite:
    try:
        _unknown(raw, _FILE_KEYS, "suite")
        cases = []
        for item in raw.get("cases") or ():
            if not isinstance(item, Mapping):
                raise ConfigurationError("each case must be an object")
            _unknown(item, _CASE_KEYS, "case")
            cases.append(
                BenchmarkCase(
                    id=item["id"],
                    name=item.get("name") or item["id"],
                    description=item.get("description") or "",
                    payload=item.get("payload"),
                    expected=item.get("expected"),
                    tags=tuple(item.get("tags") or ()),
                    metadata=item.get("metadata") or {},
                    timeout_seconds=item.get("timeout_seconds"),
                    workspace_template=_resolve_path(item.get("workspace_template"), base_dir),
                    validation_command=item.get("validation_command"),
                )
            )
        variants = []
        for item in raw.get("variants") or ():
            if not isinstance(item, Mapping):
                raise ConfigurationError("each variant must be an object")
            _unknown(item, _VARIANT_KEYS, "variant")
            variants.append(
                Variant(
                    id=item["id"],
                    name=item.get("name") or item["id"],
                    description=item.get("description") or "",
                    config=item.get("config") or {},
                    tags=tuple(item.get("tags") or ()),
                )
            )
        budget_raw = raw.get("budget") or {}
        if budget_raw:
            if not isinstance(budget_raw, Mapping):
                raise ConfigurationError("budget must be an object")
            _unknown(budget_raw, _BUDGET_KEYS, "budget")
        budget = ExecutionBudget(
            max_runs=budget_raw.get("max_runs"),
            per_run_timeout_seconds=budget_raw.get("per_run_timeout_seconds", 60.0),
            max_total_duration_seconds=budget_raw.get("max_total_duration_seconds"),
            max_total_cost=budget_raw.get("max_total_cost"),
            max_failures=budget_raw.get("max_failures"),
            per_run_max_cost=budget_raw.get("per_run_max_cost"),
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
            cases=tuple(cases),
            variants=tuple(variants),
            repetitions=raw.get("repetitions", 1),
            seed=raw.get("seed", 0),
            budget=budget,
            metrics=metrics,
            baseline_variant_id=raw.get("baseline") or raw.get("baseline_variant_id"),
            metadata=raw.get("metadata") or {},
            workspace_template=_resolve_path(raw.get("workspace_template"), base_dir),
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
            script = _resolve_path(script, base_dir) or script
            argv = default_python_argv(script)
        cwd = target.get("cwd")
        if isinstance(cwd, str):
            cwd = _resolve_path(cwd, base_dir)
        return CommandTarget(
            argv,
            cwd=cwd,
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
    if not isinstance(block, Mapping):
        raise ConfigurationError("pricing must be an object")
    extra = sorted(set(block) - {"input_token_rate", "output_token_rate"})
    if extra:
        raise ConfigurationError(f"unknown pricing field(s): {extra}")
    return PricingConfig(
        input_token_rate=block.get("input_token_rate"),
        output_token_rate=block.get("output_token_rate"),
    )


def load_validated_config(path: str | Path) -> dict[str, Any]:
    """Parse every run-relevant config section. Does not execute a target."""
    file_path = Path(path)
    raw = _load_raw(file_path)
    base = file_path.parent
    suite = suite_from_dict(raw, base_dir=base)
    target = load_target(raw, base_dir=base)
    evaluators = load_evaluators(raw)
    policy = load_policy(raw)
    pricing = load_pricing(raw)
    return {
        "raw": raw,
        "suite": suite,
        "target": target,
        "evaluators": evaluators,
        "policy": policy,
        "pricing": pricing,
    }
