"""Mutate the working directory (the isolated copy, not the template)."""

from __future__ import annotations

from pathlib import Path

Path("created.txt").write_text("hello", encoding="utf-8")
if Path("seed.txt").exists():
    Path("seed.txt").write_text("changed", encoding="utf-8")
raise SystemExit(0)
