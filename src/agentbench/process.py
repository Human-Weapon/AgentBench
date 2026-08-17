"""Cross-platform process-tree execution with bounded stdout/stderr."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence

from .numbers import require_int

DEFAULT_MAX_OUTPUT_BYTES = 1_048_576
_CHUNK = 65_536


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:  # pragma: no cover - already reaped
        return
    if os.name == "nt":
        subprocess.run(  # noqa: S603
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            shell=False,
        )
    else:  # pragma: no cover - POSIX
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
        try:
            proc.kill()
        except OSError:
            pass


def run_bounded(
    argv: Sequence[str],
    *,
    cwd: str | None,
    env: Mapping[str, str] | None,
    timeout: float | None,
    stdin_text: str | None,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> tuple[int | None, bytes, bytes, bool, bool, bool, float]:
    """Run argv in a new process group. Returns.

    (exit_code, stdout, stderr, timed_out, stdout_truncated, stderr_truncated, duration)
    """
    max_stdout_bytes = require_int(max_stdout_bytes, name="max_stdout_bytes", minimum=0)
    max_stderr_bytes = require_int(max_stderr_bytes, name="max_stderr_bytes", minimum=0)
    kwargs: dict = {
        "args": list(argv),
        "cwd": cwd,
        "env": dict(env) if env is not None else None,
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:  # pragma: no cover - POSIX
        kwargs["start_new_session"] = True

    started = time.perf_counter()
    try:
        proc = subprocess.Popen(**kwargs)  # noqa: S603
    except OSError:
        raise

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    flags = {"out": False, "err": False}

    def _reader(stream: object, chunks: list[bytes], limit: int, key: str) -> None:
        kept = 0
        try:
            while True:
                data = stream.read(_CHUNK)  # type: ignore[union-attr]
                if not data:
                    break
                if kept < limit:
                    take = data[: limit - kept]
                    chunks.append(take)
                    kept += len(take)
                    if kept >= limit:
                        flags[key] = True
                elif data:
                    flags[key] = True
        except OSError:  # pragma: no cover - reader teardown
            return

    t_out = threading.Thread(
        target=_reader, args=(proc.stdout, stdout_chunks, max_stdout_bytes, "out"), daemon=True
    )
    t_err = threading.Thread(
        target=_reader, args=(proc.stderr, stderr_chunks, max_stderr_bytes, "err"), daemon=True
    )
    t_out.start()
    t_err.start()
    if stdin_text is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin_text.encode("utf-8"))
        except OSError:  # pragma: no cover
            pass
        try:
            proc.stdin.close()
        except OSError:  # pragma: no cover
            pass
    elif proc.stdin is not None:  # pragma: no cover - stdin already closed
        try:
            proc.stdin.close()
        except OSError:
            pass

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    duration = time.perf_counter() - started
    code = proc.poll()
    return (
        None if timed_out else code,
        b"".join(stdout_chunks),
        b"".join(stderr_chunks),
        timed_out,
        flags["out"],
        flags["err"],
        duration,
    )
