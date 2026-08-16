"""Domain exception hierarchy for AgentBench.

Public boundaries raise these types instead of leaking KeyError / TypeError /
AttributeError for caller mistakes.
"""

from __future__ import annotations


class AgentBenchError(Exception):
    """Base exception for all AgentBench errors."""

    exit_code = 1


class ConfigurationError(AgentBenchError):
    """Invalid suite, experiment, or CLI configuration."""

    exit_code = 1


class ValidationError(AgentBenchError):
    """A value failed domain validation (type, range, uniqueness)."""

    exit_code = 1


class BudgetExceededError(AgentBenchError):
    """A hard execution budget would be violated by the next run."""

    exit_code = 3


class TargetExecutionError(AgentBenchError):
    """Infrastructure failure while invoking a target (not a target FAILURE)."""

    exit_code = 1


class PersistenceError(AgentBenchError):
    """Base for storage/IO persistence failures (domain-neutral)."""

    exit_code = 1


class CorruptResultError(PersistenceError):
    """Persisted JSON is syntactically or schematically invalid."""

    exit_code = 4

    def __init__(self, message: str, quarantined_path: str | None = None) -> None:
        super().__init__(message)
        self.quarantined_path = quarantined_path


class PathEscapeError(PersistenceError):
    """A resolved path escaped the configured output or workspace root."""

    exit_code = 1


class SourceMutationError(AgentBenchError):
    """A benchmark template/source directory was mutated during a run."""

    exit_code = 1
