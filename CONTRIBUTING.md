# Contributing to AgentBench

Thanks for considering contributing. AgentBench is part of the HERMES OSS ecosystem. By participating you agree to: **USEFUL ALONE + BETTER TOGETHER**, security by default, auditability, and evidence over confidence.

## Before you start

- **SEARCH before you create** — check whether the feature already exists or belongs in a sibling (PromptGraph, AgentGear, SkillGuard, ProjectKaizen). AgentBench's job is **measurement only**.
- **EXTEND before you duplicate** — improve existing modules instead of adding overlapping ones.
- Do not add LLM provider SDKs, dashboards, databases, or a sandbox in v0.1.x.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Quality checks

```bash
pytest
ruff check src/ tests/
ruff format src/ tests/
python -m build
```

## Commit conventions

Small, focused commits with conventional prefixes:

`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `perf:`, `security:`, `chore:`

Never commit secrets. Run `git diff` + `ruff` + `pytest` before committing.

## Standards

- No telemetry and no phone-home.
- Standalone by default. Optional sibling integration must degrade gracefully.
- Evidence > confidence. Do not claim statistical significance you did not compute.
- Missing metrics stay unknown. Never coerce them to zero.
- `pytest` + `ruff check` must be green before merge.
- Critical defects need a regression test that fails on the broken behavior and passes on the fix.
