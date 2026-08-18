"""Immutable, validated domain models for AgentBench."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .errors import ValidationError
from .numbers import (
    deep_freeze,
    optional_int,
    optional_number,
    require_bool,
    require_int,
    require_nonblank_str,
    require_number,
)
from .paths import safe_id

SCHEMA_VERSION = 1


class RunStatus(str, Enum):
    """Explicit run / target outcome.

    ``SUCCESS`` / ``FAILURE`` / ``TIMEOUT`` / ``SKIPPED`` are *benchmark data*.
    ``ERROR`` is an infrastructure failure and is distinguishable from a
    target that simply did not meet its own success criteria.
    """

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class MetricDirection(str, Enum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"

    @classmethod
    def parse(cls, value: object) -> MetricDirection:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError as exc:
                raise ValidationError(f"unknown metric direction: {value!r}") from exc
        raise ValidationError(f"direction must be a MetricDirection; got {type(value).__name__}")


class RegressionClass(str, Enum):
    IMPROVED = "IMPROVED"
    UNCHANGED = "UNCHANGED"
    REGRESSED = "REGRESSED"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNAVAILABLE = "UNAVAILABLE"


class MissingMetricBehavior(str, Enum):
    SKIP = "skip"
    FAIL = "fail"
    UNKNOWN = "unknown"


def _freeze_map(value: Mapping[str, Any] | None) -> Any:
    if value is None:
        return deep_freeze({})
    if not isinstance(value, Mapping):
        raise ValidationError(f"metadata must be a mapping; got {type(value).__name__}")
    return deep_freeze(dict(value))


def _freeze_tags(tags: Sequence[str] | None) -> tuple[str, ...]:
    if tags is None:
        return ()
    if isinstance(tags, (str, bytes)):
        raise ValidationError("tags must be a sequence of strings, not a single string")
    out: list[str] = []
    for item in tags:
        out.append(require_nonblank_str(item, name="tag"))
    return tuple(out)


def _argv(value: Any, *, name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValidationError(f"{name} must be an argv list of strings, not a shell string")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValidationError(f"{name} must be a sequence of strings")
    if not value:
        raise ValidationError(f"{name} must be a non-empty argv list")
    parts: list[str] = []
    for item in value:
        if not isinstance(item, str) or item == "":
            raise ValidationError(f"{name} entries must be non-empty strings")
        parts.append(item)
    return tuple(parts)


@dataclass(frozen=True)
class ExecutionBudget:
    """Hard limits for an experiment. ``None`` means unlimited.

    ``max_runs=N`` allows exactly N physical runs; the N+1st is rejected
    *before* it starts. ``0`` allows zero runs. Negatives and bools are
    rejected at construction.
    """

    max_runs: int | None = None
    per_run_timeout_seconds: float = 60.0
    max_total_duration_seconds: float | None = None
    max_total_cost: float | None = None
    max_failures: int | None = None
    per_run_max_cost: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_runs",
            optional_int(self.max_runs, name="max_runs", allow_zero=True, minimum=0),
        )
        object.__setattr__(
            self,
            "per_run_timeout_seconds",
            require_number(
                self.per_run_timeout_seconds,
                name="per_run_timeout_seconds",
                allow_zero=True,
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "max_total_duration_seconds",
            optional_number(
                self.max_total_duration_seconds,
                name="max_total_duration_seconds",
                allow_zero=True,
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "max_total_cost",
            optional_number(
                self.max_total_cost,
                name="max_total_cost",
                allow_zero=True,
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "max_failures",
            optional_int(self.max_failures, name="max_failures", allow_zero=True, minimum=0),
        )
        object.__setattr__(
            self,
            "per_run_max_cost",
            optional_number(
                self.per_run_max_cost, name="per_run_max_cost", allow_zero=True, minimum=0.0
            ),
        )
        if self.max_total_cost is not None and self.per_run_max_cost is None:
            raise ValidationError(
                "max_total_cost requires per_run_max_cost (pre-run reservation); "
                "UNKNOWN cost cannot be treated as free"
            )


@dataclass(frozen=True)
class PricingConfig:
    """Caller-supplied rates. AgentBench never invents vendor prices."""

    input_token_rate: float | None = None
    output_token_rate: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "input_token_rate",
            optional_number(self.input_token_rate, name="input_token_rate", allow_zero=True),
        )
        object.__setattr__(
            self,
            "output_token_rate",
            optional_number(self.output_token_rate, name="output_token_rate", allow_zero=True),
        )

    def estimate(self, input_tokens: float | None, output_tokens: float | None) -> float | None:
        """Estimate cost from tokens. Returns ``None`` if any input is unknown."""
        if self.input_token_rate is None or self.output_token_rate is None:
            return None
        if input_tokens is None or output_tokens is None:
            return None
        return self.input_token_rate * input_tokens + self.output_token_rate * output_tokens


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    name: str
    description: str = ""
    payload: Any = None
    expected: Any = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None
    workspace_template: str | None = None
    validation_command: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", safe_id(require_nonblank_str(self.id, name="case.id")))
        object.__setattr__(self, "name", require_nonblank_str(self.name, name="case.name"))
        if not isinstance(self.description, str):
            raise ValidationError("case.description must be a string")
        object.__setattr__(self, "tags", _freeze_tags(self.tags))
        object.__setattr__(self, "metadata", _freeze_map(self.metadata))
        object.__setattr__(self, "payload", deep_freeze(self.payload))
        object.__setattr__(self, "expected", deep_freeze(self.expected))
        object.__setattr__(
            self,
            "timeout_seconds",
            optional_number(self.timeout_seconds, name="timeout_seconds", allow_zero=True),
        )
        if self.workspace_template is not None and not isinstance(self.workspace_template, str):
            raise ValidationError("workspace_template must be a string path")
        if self.validation_command is not None:
            object.__setattr__(
                self,
                "validation_command",
                _argv(self.validation_command, name="validation_command"),
            )


@dataclass(frozen=True)
class Variant:
    """Opaque configuration being compared. AgentBench does not rank models."""

    id: str
    name: str
    description: str = ""
    config: Mapping[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", safe_id(require_nonblank_str(self.id, name="variant.id")))
        object.__setattr__(self, "name", require_nonblank_str(self.name, name="variant.name"))
        if not isinstance(self.description, str):
            raise ValidationError("variant.description must be a string")
        object.__setattr__(self, "config", _freeze_map(self.config))
        object.__setattr__(self, "tags", _freeze_tags(self.tags))


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    direction: MetricDirection
    minimum: float | None = None
    maximum: float | None = None
    weight: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonblank_str(self.name, name="metric.name"))
        object.__setattr__(self, "direction", MetricDirection.parse(self.direction))
        object.__setattr__(
            self, "minimum", optional_number(self.minimum, name="minimum", allow_negative=True)
        )
        object.__setattr__(
            self, "maximum", optional_number(self.maximum, name="maximum", allow_negative=True)
        )
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValidationError(f"metric {self.name}: minimum > maximum")
        object.__setattr__(
            self,
            "weight",
            optional_number(self.weight, name="weight", allow_zero=True, minimum=0.0),
        )


@dataclass(frozen=True)
class MetricValue:
    name: str
    value: float | None
    unit: str = ""
    source: str = "measured"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_nonblank_str(self.name, name="metric_value.name"))
        object.__setattr__(
            self,
            "value",
            optional_number(self.value, name="metric_value.value", allow_negative=True),
        )
        if not isinstance(self.unit, str):
            raise ValidationError("unit must be a string")
        if not isinstance(self.source, str):
            raise ValidationError("source must be a string")


@dataclass(frozen=True)
class Telemetry:
    """Optional measured fields. Missing stays ``None`` (UNKNOWN), never 0."""

    input_tokens: float | None = None
    output_tokens: float | None = None
    total_tokens: float | None = None
    cost: float | None = None
    latency_seconds: float | None = None
    tool_calls: int | None = None
    agent_count: int | None = None
    retries: int | None = None
    recoveries: int | None = None
    stalls: int | None = None
    errors: int | None = None
    files_created: int | None = None
    files_modified: int | None = None
    files_deleted: int | None = None
    tests_passed: int | None = None
    tests_failed: int | None = None
    stall_count: int | None = None
    recovery_attempts: int | None = None
    successful_recoveries: int | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        floats = (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "cost",
            "latency_seconds",
        )
        ints = (
            "tool_calls",
            "agent_count",
            "retries",
            "recoveries",
            "stalls",
            "errors",
            "files_created",
            "files_modified",
            "files_deleted",
            "tests_passed",
            "tests_failed",
            "stall_count",
            "recovery_attempts",
            "successful_recoveries",
        )
        for key in floats:
            object.__setattr__(
                self,
                key,
                optional_number(getattr(self, key), name=f"telemetry.{key}", allow_zero=True),
            )
        for key in ints:
            object.__setattr__(
                self,
                key,
                optional_int(
                    getattr(self, key), name=f"telemetry.{key}", allow_zero=True, minimum=0
                ),
            )
        object.__setattr__(self, "extra", _freeze_map(self.extra))

    def merge(self, **updates: Any) -> Telemetry:
        data = {f.name: getattr(self, f.name) for f in self.__dataclass_fields__.values()}
        data.update(updates)
        return Telemetry(**data)

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
            "latency_seconds": self.latency_seconds,
            "tool_calls": self.tool_calls,
            "agent_count": self.agent_count,
            "retries": self.retries,
            "recoveries": self.recoveries,
            "stalls": self.stalls,
            "errors": self.errors,
            "files_created": self.files_created,
            "files_modified": self.files_modified,
            "files_deleted": self.files_deleted,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "stall_count": self.stall_count,
            "recovery_attempts": self.recovery_attempts,
            "successful_recoveries": self.successful_recoveries,
            "extra": dict(self.extra),
        }


@dataclass(frozen=True)
class WorkspaceDiff:
    files_created: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    bytes_changed: int = 0
    created_paths: tuple[str, ...] = ()
    modified_paths: tuple[str, ...] = ()
    deleted_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for key in ("files_created", "files_modified", "files_deleted", "bytes_changed"):
            object.__setattr__(
                self,
                key,
                require_int(getattr(self, key), name=key, allow_zero=True, minimum=0),
            )


@dataclass(frozen=True)
class TargetResult:
    status: RunStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_seconds: float = 0.0
    structured_output: Any = None
    telemetry: Telemetry = field(default_factory=Telemetry)
    artifacts: Mapping[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    timed_out: bool = False
    infrastructure_error: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            try:
                object.__setattr__(self, "status", RunStatus(self.status))
            except ValueError as exc:
                raise ValidationError(f"unknown status: {self.status!r}") from exc
        if not isinstance(self.status, RunStatus):
            raise ValidationError("status must be a RunStatus")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise ValidationError("stdout/stderr must be strings")
        object.__setattr__(
            self,
            "exit_code",
            optional_int(self.exit_code, name="exit_code", allow_negative=True),
        )
        object.__setattr__(
            self,
            "duration_seconds",
            require_number(self.duration_seconds, name="duration_seconds", allow_zero=True),
        )
        if not isinstance(self.telemetry, Telemetry):
            raise ValidationError("telemetry must be a Telemetry instance")
        object.__setattr__(self, "artifacts", _freeze_map(self.artifacts))
        object.__setattr__(self, "timed_out", require_bool(self.timed_out, name="timed_out"))
        object.__setattr__(
            self,
            "infrastructure_error",
            require_bool(self.infrastructure_error, name="infrastructure_error"),
        )
        if self.timed_out and self.status is not RunStatus.TIMEOUT:
            raise ValidationError("timed_out=True requires status=TIMEOUT")
        if self.status is RunStatus.TIMEOUT and not self.timed_out:
            object.__setattr__(self, "timed_out", True)
        if self.infrastructure_error and self.status is not RunStatus.ERROR:
            raise ValidationError("infrastructure_error=True requires status=ERROR")

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "structured_output": self.structured_output,
            "telemetry": self.telemetry.as_dict(),
            "artifacts": dict(self.artifacts),
            "error_message": self.error_message,
            "timed_out": self.timed_out,
            "infrastructure_error": self.infrastructure_error,
        }


@dataclass(frozen=True)
class EvaluationResult:
    evaluator: str
    passed: bool | None
    score: float | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evaluator", require_nonblank_str(self.evaluator, name="evaluator")
        )
        if self.passed is not None and not isinstance(self.passed, bool):
            raise ValidationError("passed must be bool or None")
        object.__setattr__(
            self, "score", optional_number(self.score, name="score", allow_negative=True)
        )
        object.__setattr__(self, "details", _freeze_map(self.details))

    def as_dict(self) -> dict[str, Any]:
        return {
            "evaluator": self.evaluator,
            "passed": self.passed,
            "score": self.score,
            "details": dict(self.details),
            "error": self.error,
        }


@dataclass(frozen=True)
class RunResult:
    run_id: str
    case_id: str
    variant_id: str
    repetition: int
    seed: int
    target: TargetResult
    evaluations: tuple[EvaluationResult, ...] = ()
    workspace_diff: WorkspaceDiff | None = None
    started_at: str = ""
    finished_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", safe_id(self.run_id, name="run_id"))
        object.__setattr__(self, "case_id", safe_id(self.case_id, name="case_id"))
        object.__setattr__(self, "variant_id", safe_id(self.variant_id, name="variant_id"))
        object.__setattr__(
            self,
            "repetition",
            require_int(self.repetition, name="repetition", allow_zero=True, minimum=0),
        )
        object.__setattr__(self, "seed", require_int(self.seed, name="seed", allow_negative=True))
        if not isinstance(self.target, TargetResult):
            raise ValidationError("target must be a TargetResult")
        if not isinstance(self.evaluations, tuple):
            object.__setattr__(self, "evaluations", tuple(self.evaluations))
        object.__setattr__(
            self,
            "schema_version",
            require_int(self.schema_version, name="schema_version", minimum=1),
        )

    @property
    def validation_passed(self) -> bool | None:
        """``False`` if any evaluator failed; ``None`` if none ran; else ``True``."""
        if not self.evaluations:
            return None
        if any(ev.passed is False for ev in self.evaluations):
            return False
        if any(ev.passed is None and ev.error for ev in self.evaluations):
            return False
        return True

    @property
    def target_succeeded(self) -> bool:
        return self.target.status is RunStatus.SUCCESS

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "case_id": self.case_id,
            "variant_id": self.variant_id,
            "repetition": self.repetition,
            "seed": self.seed,
            "target": self.target.as_dict(),
            "evaluations": [ev.as_dict() for ev in self.evaluations],
            "workspace_diff": None
            if self.workspace_diff is None
            else {
                "files_created": self.workspace_diff.files_created,
                "files_modified": self.workspace_diff.files_modified,
                "files_deleted": self.workspace_diff.files_deleted,
                "bytes_changed": self.workspace_diff.bytes_changed,
                "created_paths": list(self.workspace_diff.created_paths),
                "modified_paths": list(self.workspace_diff.modified_paths),
                "deleted_paths": list(self.workspace_diff.deleted_paths),
            },
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class BenchmarkSuite:
    id: str
    name: str
    cases: tuple[BenchmarkCase, ...]
    variants: tuple[Variant, ...]
    description: str = ""
    repetitions: int = 1
    seed: int = 0
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    metrics: tuple[MetricDefinition, ...] = ()
    baseline_variant_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    workspace_template: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", safe_id(require_nonblank_str(self.id, name="suite.id")))
        object.__setattr__(self, "name", require_nonblank_str(self.name, name="suite.name"))
        if not isinstance(self.description, str):
            raise ValidationError("suite.description must be a string")
        if not self.cases:
            raise ValidationError("suite must contain at least one case")
        if not self.variants:
            raise ValidationError("suite must contain at least one variant")
        cases = tuple(self.cases)
        variants = tuple(self.variants)
        case_ids = [c.id for c in cases]
        variant_ids = [v.id for v in variants]
        if len(case_ids) != len(set(case_ids)):
            raise ValidationError(f"duplicate case id in suite {self.id}")
        if len(variant_ids) != len(set(variant_ids)):
            raise ValidationError(f"duplicate variant id in suite {self.id}")
        object.__setattr__(self, "cases", cases)
        object.__setattr__(self, "variants", variants)
        object.__setattr__(
            self,
            "repetitions",
            require_int(self.repetitions, name="repetitions", allow_zero=False, minimum=1),
        )
        object.__setattr__(self, "seed", require_int(self.seed, name="seed", allow_negative=True))
        if not isinstance(self.budget, ExecutionBudget):
            raise ValidationError("budget must be an ExecutionBudget")
        object.__setattr__(self, "metrics", tuple(self.metrics))
        object.__setattr__(self, "metadata", _freeze_map(self.metadata))
        if self.baseline_variant_id is not None:
            bid = safe_id(self.baseline_variant_id, name="baseline_variant_id")
            if bid not in variant_ids:
                raise ValidationError(f"baseline variant {bid!r} is not in the suite")
            object.__setattr__(self, "baseline_variant_id", bid)

    def case_by_id(self, case_id: str) -> BenchmarkCase:
        for case in self.cases:
            if case.id == case_id:
                return case
        raise ValidationError(f"unknown case id: {case_id}")

    def variant_by_id(self, variant_id: str) -> Variant:
        for variant in self.variants:
            if variant.id == variant_id:
                return variant
        raise ValidationError(f"unknown variant id: {variant_id}")

    def planned_runs(self) -> int:
        return len(self.cases) * len(self.variants) * self.repetitions


@dataclass(frozen=True)
class EnvironmentFingerprint:
    agentbench_version: str
    python_version: str
    platform: str
    os_name: str
    architecture: str
    seed: int
    timestamp: str
    cwd_policy: str
    git_sha: str | None = None
    target_metadata: Mapping[str, Any] = field(default_factory=dict)
    extra: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agentbench_version": self.agentbench_version,
            "python_version": self.python_version,
            "platform": self.platform,
            "os_name": self.os_name,
            "architecture": self.architecture,
            "seed": self.seed,
            "timestamp": self.timestamp,
            "cwd_policy": self.cwd_policy,
            "git_sha": self.git_sha,
            "target_metadata": dict(self.target_metadata),
            "extra": dict(self.extra),
        }


def make_run_id(suite_id: str, case_id: str, variant_id: str, repetition: int, seed: int) -> str:
    """Deterministic, filesystem-safe run identifier."""
    return (
        f"{safe_id(suite_id, name='suite_id')}__"
        f"{safe_id(case_id, name='case_id')}__"
        f"{safe_id(variant_id, name='variant_id')}__"
        f"r{require_int(repetition, name='repetition', allow_zero=True)}__"
        f"s{require_int(seed, name='seed', allow_negative=True)}"
    )
