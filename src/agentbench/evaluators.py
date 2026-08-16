"""Deterministic evaluators. No eval(), no arbitrary assertion code."""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from .errors import ValidationError
from .models import EvaluationResult, RunStatus, TargetResult, WorkspaceDiff
from .numbers import require_int


@runtime_checkable
class Evaluator(Protocol):
    name: str

    def evaluate(self, context: Mapping[str, Any]) -> EvaluationResult: ...  # pragma: no cover


def _target(context: Mapping[str, Any]) -> TargetResult:
    target = context.get("target")
    if not isinstance(target, TargetResult):
        raise ValidationError("evaluator context is missing TargetResult")
    return target


class ExitCodeEvaluator:
    name = "exit_code"

    def __init__(self, expected: int = 0) -> None:
        self.expected = require_int(expected, name="expected", allow_negative=True)

    def evaluate(self, context: Mapping[str, Any]) -> EvaluationResult:
        target = _target(context)
        passed = target.exit_code == self.expected
        return EvaluationResult(
            evaluator=self.name,
            passed=passed,
            details={"expected": self.expected, "actual": target.exit_code},
        )


class ExactTextEvaluator:
    name = "exact_text"

    def __init__(self, expected: str, *, source: str = "stdout") -> None:
        if not isinstance(expected, str):
            raise ValidationError("expected must be a string")
        if source not in {"stdout", "stderr"}:
            raise ValidationError("source must be stdout or stderr")
        self.expected = expected
        self.source = source

    def evaluate(self, context: Mapping[str, Any]) -> EvaluationResult:
        target = _target(context)
        actual = target.stdout if self.source == "stdout" else target.stderr
        return EvaluationResult(
            evaluator=self.name,
            passed=actual == self.expected,
            details={"source": self.source, "expected": self.expected, "actual": actual},
        )


class ContainsTextEvaluator:
    name = "contains_text"

    def __init__(self, needle: str, *, source: str = "stdout") -> None:
        if not isinstance(needle, str) or needle == "":
            raise ValidationError("needle must be a non-empty string")
        if source not in {"stdout", "stderr"}:
            raise ValidationError("source must be stdout or stderr")
        self.needle = needle
        self.source = source

    def evaluate(self, context: Mapping[str, Any]) -> EvaluationResult:
        target = _target(context)
        haystack = target.stdout if self.source == "stdout" else target.stderr
        return EvaluationResult(
            evaluator=self.name,
            passed=self.needle in haystack,
            details={"source": self.source, "needle": self.needle},
        )


class RegexEvaluator:
    name = "regex"

    def __init__(self, pattern: str, *, source: str = "stdout") -> None:
        if not isinstance(pattern, str) or not pattern:
            raise ValidationError("pattern must be a non-empty string")
        if source not in {"stdout", "stderr"}:
            raise ValidationError("source must be stdout or stderr")
        try:
            self.compiled = re.compile(pattern)
        except re.error as exc:
            raise ValidationError(f"invalid regex: {exc}") from exc
        self.pattern = pattern
        self.source = source

    def evaluate(self, context: Mapping[str, Any]) -> EvaluationResult:
        target = _target(context)
        haystack = target.stdout if self.source == "stdout" else target.stderr
        match = self.compiled.search(haystack)
        return EvaluationResult(
            evaluator=self.name,
            passed=match is not None,
            details={"pattern": self.pattern, "source": self.source},
        )


class JsonFieldEvaluator:
    name = "json_field"

    def __init__(self, field_path: str, expected: Any, *, source: str = "structured") -> None:
        if not isinstance(field_path, str) or not field_path.strip():
            raise ValidationError("field_path must be a dotted path")
        self.field_path = field_path.strip()
        self.expected = expected
        self.source = source

    def _lookup(self, payload: Any) -> Any:
        current = payload
        for part in self.field_path.split("."):
            if isinstance(current, Mapping) and part in current:
                current = current[part]
            else:
                return None
        return current

    def evaluate(self, context: Mapping[str, Any]) -> EvaluationResult:
        target = _target(context)
        if self.source == "structured":
            payload = target.structured_output
        else:
            try:
                payload = json.loads(target.stdout)
            except json.JSONDecodeError:
                return EvaluationResult(
                    evaluator=self.name,
                    passed=False,
                    details={"error": "stdout is not JSON"},
                )
        actual = self._lookup(payload)
        return EvaluationResult(
            evaluator=self.name,
            passed=actual == self.expected,
            details={"path": self.field_path, "expected": self.expected, "actual": actual},
        )


class ValidationCommandEvaluator:
    """Run an argv validation command in the run workspace. Never a shell string."""

    name = "validation_command"

    def __init__(self, argv: Sequence[str], *, timeout_seconds: float = 60.0) -> None:
        if isinstance(argv, (str, bytes)):
            raise ValidationError("validation command must be an argv list, not a shell string")
        if not argv:
            raise ValidationError("validation command argv must be non-empty")
        cleaned = []
        for item in argv:
            if not isinstance(item, str) or item == "":
                raise ValidationError("validation argv entries must be non-empty strings")
            cleaned.append(item)
        self.argv = tuple(cleaned)
        from .numbers import require_number

        self.timeout_seconds = require_number(
            timeout_seconds, name="timeout_seconds", allow_zero=True
        )

    def evaluate(self, context: Mapping[str, Any]) -> EvaluationResult:
        cwd = context.get("cwd")
        started = time.perf_counter()
        try:
            completed = subprocess.run(  # noqa: S603
                list(self.argv),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - started
            return EvaluationResult(
                evaluator=self.name,
                passed=False,
                details={
                    "timeout": True,
                    "duration_seconds": duration,
                    "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                    "stderr": (exc.stderr or "") if isinstance(exc.stderr, str) else "",
                },
                error=f"validation timed out after {self.timeout_seconds}s",
            )
        except OSError as exc:
            return EvaluationResult(
                evaluator=self.name,
                passed=False,
                details={"spawn_error": str(exc)},
                error=str(exc),
            )
        duration = time.perf_counter() - started
        passed = completed.returncode == 0
        return EvaluationResult(
            evaluator=self.name,
            passed=passed,
            details={
                "exit_code": completed.returncode,
                "duration_seconds": duration,
                "stdout": completed.stdout or "",
                "stderr": completed.stderr or "",
                "argv": list(self.argv),
            },
        )


class FileChangeEvaluator:
    name = "file_change"

    def __init__(
        self,
        *,
        min_created: int = 0,
        min_modified: int = 0,
        min_deleted: int = 0,
    ) -> None:
        self.min_created = require_int(min_created, name="min_created", allow_zero=True)
        self.min_modified = require_int(min_modified, name="min_modified", allow_zero=True)
        self.min_deleted = require_int(min_deleted, name="min_deleted", allow_zero=True)

    def evaluate(self, context: Mapping[str, Any]) -> EvaluationResult:
        diff = context.get("workspace_diff")
        if not isinstance(diff, WorkspaceDiff):
            return EvaluationResult(
                evaluator=self.name,
                passed=False,
                details={},
                error="workspace_diff missing",
            )
        passed = (
            diff.files_created >= self.min_created
            and diff.files_modified >= self.min_modified
            and diff.files_deleted >= self.min_deleted
        )
        return EvaluationResult(
            evaluator=self.name,
            passed=passed,
            details={
                "created": diff.files_created,
                "modified": diff.files_modified,
                "deleted": diff.files_deleted,
            },
        )


class TestsPassedEvaluator:
    name = "tests_passed"

    def evaluate(self, context: Mapping[str, Any]) -> EvaluationResult:
        target = _target(context)
        passed_n = target.telemetry.tests_passed
        failed_n = target.telemetry.tests_failed
        if passed_n is None and failed_n is None:
            return EvaluationResult(
                evaluator=self.name,
                passed=None,
                details={},
                error="tests_passed/tests_failed telemetry unknown",
            )
        failed_n = 0 if failed_n is None else failed_n
        passed_n = 0 if passed_n is None else passed_n
        ok = failed_n == 0 and passed_n > 0
        return EvaluationResult(
            evaluator=self.name,
            passed=ok,
            score=float(passed_n),
            details={"tests_passed": passed_n, "tests_failed": failed_n},
        )


class TargetStatusEvaluator:
    """Require the target itself to report SUCCESS. Distinct from validation."""

    name = "target_status"

    def __init__(self, expected: RunStatus = RunStatus.SUCCESS) -> None:
        self.expected = expected if isinstance(expected, RunStatus) else RunStatus(expected)

    def evaluate(self, context: Mapping[str, Any]) -> EvaluationResult:
        target = _target(context)
        return EvaluationResult(
            evaluator=self.name,
            passed=target.status is self.expected,
            details={"expected": self.expected.value, "actual": target.status.value},
        )


def evaluator_from_config(raw: Mapping[str, Any]) -> Evaluator:
    if not isinstance(raw, Mapping):
        raise ValidationError("evaluator config must be an object")
    kind = raw.get("type")
    if kind == "exit_code":
        return ExitCodeEvaluator(expected=raw.get("expected", 0))
    if kind == "exact_text":
        return ExactTextEvaluator(raw["expected"], source=raw.get("source", "stdout"))
    if kind == "contains_text":
        return ContainsTextEvaluator(raw["needle"], source=raw.get("source", "stdout"))
    if kind == "regex":
        return RegexEvaluator(raw["pattern"], source=raw.get("source", "stdout"))
    if kind == "json_field":
        return JsonFieldEvaluator(
            raw["field"], raw.get("expected"), source=raw.get("source", "structured")
        )
    if kind == "validation_command":
        return ValidationCommandEvaluator(
            raw["argv"], timeout_seconds=raw.get("timeout_seconds", 60.0)
        )
    if kind == "file_change":
        return FileChangeEvaluator(
            min_created=raw.get("min_created", 0),
            min_modified=raw.get("min_modified", 0),
            min_deleted=raw.get("min_deleted", 0),
        )
    if kind == "tests_passed":
        return TestsPassedEvaluator()
    if kind == "target_status":
        return TargetStatusEvaluator(raw.get("expected", "SUCCESS"))
    raise ValidationError(f"unknown evaluator type: {kind!r}")
