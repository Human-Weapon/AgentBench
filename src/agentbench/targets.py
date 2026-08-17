"""Benchmark targets: provider-independent execution adapters.

``CommandTarget`` never uses ``shell=True``. A raw shell string is rejected.
There is no shell mode in v0.1.0.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from .errors import TargetExecutionError, ValidationError
from .models import BenchmarkCase, RunStatus, TargetResult, Telemetry, Variant
from .numbers import optional_number, reject_nonfinite_tree, require_int, require_number
from .process import DEFAULT_MAX_OUTPUT_BYTES, run_bounded


@runtime_checkable
class BenchmarkTarget(Protocol):
    def run(
        self,
        case: BenchmarkCase,
        variant: Variant,
        context: Mapping[str, Any],
    ) -> TargetResult: ...  # pragma: no cover

    def describe(self) -> dict[str, Any]: ...  # pragma: no cover


def _decode(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


def _parse_structured(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last non-empty line may be a JSON object emitted after logs.
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{") or line.startswith("["):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return None


def _telemetry_from_structured(payload: Any) -> Telemetry:
    if not isinstance(payload, Mapping):
        return Telemetry()
    tel = payload.get("telemetry")
    if tel is None:
        keys = Telemetry.__dataclass_fields__
        tel = payload if any(k in payload for k in keys if k != "extra") else {}
    if not isinstance(tel, Mapping):
        raise ValidationError("telemetry must be an object")
    reject_nonfinite_tree(tel, name="telemetry")
    fields = {k: tel.get(k) for k in Telemetry.__dataclass_fields__ if k != "extra"}
    extra = tel.get("extra") if isinstance(tel.get("extra"), Mapping) else {}
    return Telemetry(extra=extra, **fields)


class CommandTarget:
    """Black-box argv target. ``shell`` is never enabled."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        stdin_payload: bool = True,
        max_stdout_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        max_stderr_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        if isinstance(argv, (str, bytes)):
            raise ValidationError("CommandTarget argv must be a list, not a shell string")
        if not argv:
            raise ValidationError("CommandTarget argv must be non-empty")
        cleaned: list[str] = []
        for item in argv:
            if not isinstance(item, str) or item == "":
                raise ValidationError("CommandTarget argv entries must be non-empty strings")
            cleaned.append(item)
        self.argv = tuple(cleaned)
        self.cwd = os.fspath(cwd) if cwd is not None else None
        if env is not None:
            if not isinstance(env, Mapping):
                raise ValidationError("env must be a mapping of str to str")
            for key, value in env.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise ValidationError("env keys and values must be strings")
            self.env = dict(env)
        else:
            self.env = None
        self.timeout_seconds = (
            None
            if timeout_seconds is None
            else require_number(timeout_seconds, name="timeout_seconds", allow_zero=True)
        )
        self.stdin_payload = bool(stdin_payload)
        self.max_stdout_bytes = require_int(
            max_stdout_bytes, name="max_stdout_bytes", allow_zero=True, minimum=0
        )
        self.max_stderr_bytes = require_int(
            max_stderr_bytes, name="max_stderr_bytes", allow_zero=True, minimum=0
        )

    def describe(self) -> dict[str, Any]:
        return {
            "type": "command",
            "argv": list(self.argv),
            "cwd": self.cwd,
            "timeout_seconds": self.timeout_seconds,
            "shell": False,
        }

    def run(
        self,
        case: BenchmarkCase,
        variant: Variant,
        context: Mapping[str, Any],
    ) -> TargetResult:
        timeout = context.get("timeout_seconds", self.timeout_seconds)
        if timeout is not None:
            timeout = require_number(timeout, name="timeout_seconds", allow_zero=True)
        cwd = context.get("cwd", self.cwd)
        if cwd is not None:
            cwd = os.fspath(cwd)

        env = os.environ.copy()
        if self.env:
            env.update(self.env)
        extra_env = context.get("env")
        if isinstance(extra_env, Mapping):
            for key, value in extra_env.items():
                if isinstance(key, str) and isinstance(value, str):
                    env[key] = value
        env["AGENTBENCH_CASE_ID"] = case.id
        env["AGENTBENCH_VARIANT_ID"] = variant.id
        env["AGENTBENCH_RUN_ID"] = str(context.get("run_id", ""))
        env["AGENTBENCH_SEED"] = str(context.get("seed", ""))

        stdin_text = None
        if self.stdin_payload:
            stdin_text = json.dumps(
                {
                    "case": {
                        "id": case.id,
                        "name": case.name,
                        "payload": case.payload,
                        "expected": case.expected,
                    },
                    "variant": {
                        "id": variant.id,
                        "name": variant.name,
                        "config": dict(variant.config),
                    },
                    "context": {
                        "run_id": context.get("run_id"),
                        "seed": context.get("seed"),
                        "repetition": context.get("repetition"),
                    },
                },
                default=str,
            )

        started = time.perf_counter()
        try:
            code, out_b, err_b, timed_out, out_trunc, err_trunc, duration = run_bounded(
                list(self.argv),
                cwd=cwd,
                env=env,
                timeout=timeout,
                stdin_text=stdin_text,
                max_stdout_bytes=self.max_stdout_bytes,
                max_stderr_bytes=self.max_stderr_bytes,
            )
        except OSError as exc:
            duration = time.perf_counter() - started
            return TargetResult(
                status=RunStatus.ERROR,
                stdout="",
                stderr=str(exc),
                exit_code=None,
                duration_seconds=duration,
                error_message=f"failed to spawn process: {exc}",
                infrastructure_error=True,
            )

        stdout = _decode(out_b)
        stderr = _decode(err_b)
        artifacts = {
            "stdout_truncated": out_trunc,
            "stderr_truncated": err_trunc,
            "max_stdout_bytes": self.max_stdout_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
        }
        if timed_out:
            return TargetResult(
                status=RunStatus.TIMEOUT,
                stdout=stdout,
                stderr=stderr,
                exit_code=None,
                duration_seconds=duration,
                error_message=f"timeout after {timeout}s",
                timed_out=True,
                artifacts=artifacts,
            )
        try:
            structured = _parse_structured(stdout)
            telemetry = _telemetry_from_structured(structured)
        except ValidationError as exc:
            return TargetResult(
                status=RunStatus.ERROR,
                stdout=stdout,
                stderr=stderr,
                exit_code=code,
                duration_seconds=duration,
                error_message=f"invalid telemetry: {exc}",
                infrastructure_error=True,
                artifacts=artifacts,
            )
        if telemetry.latency_seconds is None:
            telemetry = telemetry.merge(latency_seconds=duration)
        status = RunStatus.SUCCESS if code == 0 else RunStatus.FAILURE
        return TargetResult(
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=code,
            duration_seconds=duration,
            structured_output=structured,
            telemetry=telemetry,
            artifacts=artifacts,
        )


class PythonCallableTarget:
    """In-process deterministic adapter. The callable is supplied by the caller."""

    def __init__(self, fn: Callable[..., Any], *, name: str = "callable") -> None:
        if not callable(fn):
            raise ValidationError("PythonCallableTarget requires a callable")
        self.fn = fn
        self.name = name

    def describe(self) -> dict[str, Any]:
        return {"type": "python_callable", "name": self.name}

    def run(
        self,
        case: BenchmarkCase,
        variant: Variant,
        context: Mapping[str, Any],
    ) -> TargetResult:
        timeout = context.get("timeout_seconds")
        if timeout is not None:
            optional_number(timeout, name="timeout_seconds", allow_zero=True)
        started = time.perf_counter()
        try:
            raw = self.fn(case, variant, context)
        except Exception as exc:  # noqa: BLE001 - target failure is data
            duration = time.perf_counter() - started
            return TargetResult(
                status=RunStatus.FAILURE,
                stderr=f"{type(exc).__name__}: {exc}",
                duration_seconds=duration,
                error_message=str(exc),
            )
        duration = time.perf_counter() - started
        if isinstance(raw, TargetResult):
            if raw.duration_seconds == 0:
                return TargetResult(
                    status=raw.status,
                    stdout=raw.stdout,
                    stderr=raw.stderr,
                    exit_code=raw.exit_code,
                    duration_seconds=duration,
                    structured_output=raw.structured_output,
                    telemetry=raw.telemetry.merge(
                        latency_seconds=raw.telemetry.latency_seconds or duration
                    ),
                    artifacts=raw.artifacts,
                    error_message=raw.error_message,
                    timed_out=raw.timed_out,
                    infrastructure_error=raw.infrastructure_error,
                )
            return raw
        if raw is None:
            return TargetResult(
                status=RunStatus.SUCCESS,
                duration_seconds=duration,
                exit_code=0,
                telemetry=Telemetry(latency_seconds=duration),
            )
        if not isinstance(raw, Mapping):
            raise TargetExecutionError(
                f"PythonCallableTarget must return TargetResult, mapping, or None; "
                f"got {type(raw).__name__}"
            )
        try:
            telemetry = _telemetry_from_structured(raw)
        except ValidationError as exc:
            raise TargetExecutionError(f"invalid telemetry: {exc}") from exc
        if telemetry.latency_seconds is None:
            telemetry = telemetry.merge(latency_seconds=duration)
        try:
            stdout = json.dumps(raw, default=str, allow_nan=False)
        except ValueError as exc:
            raise TargetExecutionError(
                f"structured output is not JSON-serializable: {exc}"
            ) from exc
        return TargetResult(
            status=RunStatus.SUCCESS,
            stdout=stdout,
            duration_seconds=duration,
            structured_output=raw,
            telemetry=telemetry,
            exit_code=0,
        )


def default_python_argv(script: str) -> tuple[str, ...]:
    """Build an argv list that invokes ``script`` with this interpreter."""
    if not isinstance(script, str) or not script:
        raise ValidationError("script path must be a non-empty string")
    return (sys.executable, script)
