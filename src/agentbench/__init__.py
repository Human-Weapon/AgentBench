"""AgentBench — objective evaluation for agents, prompts, skills, and strategies.

AgentBench MEASURES. It does not decide which model, agent, or strategy
should be used in production. That decision belongs to AgentGear or the caller.

USEFUL ALONE — BETTER TOGETHER.
"""

from __future__ import annotations

from ._version import __version__
from .adapters import AgentGearEvidenceAdapter
from .aggregation import aggregate_experiment
from .comparison import compare
from .errors import (
    AgentBenchError,
    BudgetExceededError,
    ConfigurationError,
    CorruptResultError,
    CostBoundViolationError,
    PathEscapeError,
    PersistenceError,
    SourceMutationError,
    TargetExecutionError,
    ValidationError,
)
from .evaluators import (
    ContainsTextEvaluator,
    ExactTextEvaluator,
    ExitCodeEvaluator,
    FileChangeEvaluator,
    JsonFieldEvaluator,
    RegexEvaluator,
    TestsPassedEvaluator,
    ValidationCommandEvaluator,
)
from .metrics import composite_score
from .models import (
    SCHEMA_VERSION,
    BenchmarkCase,
    BenchmarkSuite,
    ExecutionBudget,
    MetricDefinition,
    MetricDirection,
    PricingConfig,
    RegressionClass,
    RunResult,
    RunStatus,
    TargetResult,
    Telemetry,
    Variant,
)
from .regression import MetricRule, RegressionPolicy
from .report import generate_report
from .runner import ExperimentOutcome, ExperimentRunner, ExperimentSpec
from .siblings import detect_integrations
from .targets import CommandTarget, PythonCallableTarget
from .workspace import DirectoryCopyWorkspace

__all__ = [
    "SCHEMA_VERSION",
    "AgentBenchError",
    "AgentGearEvidenceAdapter",
    "BenchmarkCase",
    "BenchmarkSuite",
    "BudgetExceededError",
    "CommandTarget",
    "ConfigurationError",
    "ContainsTextEvaluator",
    "CorruptResultError",
    "CostBoundViolationError",
    "DirectoryCopyWorkspace",
    "ExactTextEvaluator",
    "ExecutionBudget",
    "ExitCodeEvaluator",
    "ExperimentOutcome",
    "ExperimentRunner",
    "ExperimentSpec",
    "FileChangeEvaluator",
    "JsonFieldEvaluator",
    "MetricDefinition",
    "MetricDirection",
    "MetricRule",
    "PathEscapeError",
    "PersistenceError",
    "PricingConfig",
    "PythonCallableTarget",
    "RegexEvaluator",
    "RegressionClass",
    "RegressionPolicy",
    "RunResult",
    "RunStatus",
    "SourceMutationError",
    "TargetExecutionError",
    "TargetResult",
    "Telemetry",
    "TestsPassedEvaluator",
    "ValidationCommandEvaluator",
    "ValidationError",
    "Variant",
    "aggregate_experiment",
    "compare",
    "composite_score",
    "detect_integrations",
    "generate_report",
    "__version__",
]
