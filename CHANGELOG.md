# Changelog

All notable changes to AgentBench are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-08-17

First stable open-source release.

Promoted candidate: `20bc72473a192f4603b52cbce8e30d43d58c148e`.
Final independent promotion verification: **PASS — PROMOTE v0.1.0**.

AgentBench is an objective benchmarking and regression-evaluation toolkit
for AI agents, prompts, skills, models, and execution strategies. It
measures; it does not choose production models or strategies.

This release was promoted after four independent adversarial audit /
remediation rounds. Earlier verdicts (D / C) are retained below as
engineering history. They are not erased by promotion.

### Shipped

- Reproducible benchmark suites with cases, variants, repetitions, and seeds
- Command targets (argv list, `shell=False`) and Python-callable targets
- Pluggable deterministic evaluators and explicit metric directions
- Baseline / candidate regression comparison, paired win rate, flakiness
- Hard execution budgets: runs, duration, failures, and cost
- Honest cost accounting (`Decimal`; UNKNOWN is never zero; measured spend
  is never clamped)
- Process timeout with descendant cleanup
- Isolated workspaces and source-immutability checks
- Structured JSON experiment persistence and human / `--json` CLI
- Wheel and sdist standalone packaging (no sibling ecosystem required)
- CI verified on Windows and Ubuntu, Python 3.10–3.12

### Remediation Round 4

- Explicit JSON `null` is no longer treated as an omitted field for
  optional-absent mappings, strings, lists, or timestamps.
- `started_at` / `finished_at` are empty or ISO-8601 strings at both
  construction and load. `None` and numbers cannot persist then fail.
- Workspace path lists are `tuple[str, ...]`. Error fields are `str | None`.

### Remediation Round 3

- Explicit `hard_gate: null` is rejected (omitted still defaults to false).
- `to_jsonable` / `deep_freeze` require string mapping keys; no key
  stringification or silent collisions.
- Closed, type-strict config schemas for suite/case/variant/target/
  evaluator/metric/budget/pricing/regression. `validate` and `run` share
  `load_validated_config`.
- Public `TargetResult` booleans must be real bools so persist/load
  round-trips.
- Persisted nested evidence is not repaired (`or {}` / `or 0` removed).
- `agentbench report` writes only through `ResultStore.write_text`.

### Remediation Round 2

- `CommandTarget` stdin uses `to_jsonable()` so frozen mappings stay JSON
  objects. The shipped example is 6 SUCCESS / 2 FAILURE.
- Regression `hard_gate` accepts only JSON booleans. `validate` now
  parses regression and pricing on the same path as `run`.
- Output-root identity is re-checked before every persist write.
- Persisted `telemetry=[]` (and other non-objects) is corrupt, not UNKNOWN.
- `PythonCallableTarget` rejects `None`.
- Paired comparison keys `(case_id, repetition, seed)` and rejects duplicates.
- Cost ledger uses `Decimal` so `0.1+0.1+0.1` vs `0.3` does not false-exhaust.
- Exact stdout/stderr cap `N` is not marked truncated.

### Remediation Round 1

- Hard cost budget now requires a pre-run `per_run_max_cost` reservation.
  UNKNOWN cost is never treated as free. If measured cost exceeds that
  reservation, AgentBench records the real spend, flags
  `cost_bound_violated`, and stops further runs (no silent clamp).
  The CLI then exits `6` (`CostBoundViolationError.exit_code`) after
  persisting evidence. A hard-gate failure remains exit `5`; if both
  apply, `6` wins.
- Case-level workspace templates use the same post-run immutability check.
- Timeouts terminate the process tree, not only the parent.
- Reusing a non-empty result directory is rejected.
- Unscheduled budget items are metadata, not synthetic `SKIPPED` run results.
- Active-run timeout is clipped to remaining `max_total_duration_seconds`.
- Nested persisted schema, deep freeze, strict config keys, config-relative
  paths, duplicate regression rules, invalid telemetry/targets, recursive
  NaN rejection, junction/symlink escape, global `--json`, bounded stdout.

### Added

- Domain models for suites, cases, variants, runs, telemetry, budgets, and reports
- `CommandTarget` (argv list, `shell=False`) and `PythonCallableTarget`
- Explicit `TIMEOUT` vs `FAILURE` vs infrastructure `ERROR`
- Isolated `DirectoryCopyWorkspace` with source-immutability check and file diffs
- Deterministic evaluators (exit code, text, regex, JSON field, validation command, file change, tests passed)
- Sequential experiment runner with incremental JSON persistence
- Hard budgets: `max_runs`, per-run timeout, total duration, total cost, max failures
- Aggregation (mean/median/min/max/stdev/p50/p95) with sample size always reported
- Baseline vs candidate comparison, paired win rate, flakiness detection
- Caller-defined `RegressionPolicy` (no invented thresholds)
- Optional quality/cost Pareto frontier (analysis, not routing)
- CLI: `validate`, `run`, `compare`, `report`, `status` (`--json`, `--debug`)
- Optional `AgentGearEvidenceAdapter` (no hard dependency)
- Sample local benchmark under `examples/`
- CI matrix: Windows + Ubuntu, Python 3.10/3.11/3.12

### Known limitations

- Sequential execution only
- No confidence intervals / statistical significance
- macOS CI is not verified
- Output containment is defensive application-level protection, not a
  kernel sandbox
- Hard-link aliases of an already-trusted file cannot be distinguished
  via `realpath`
- Callers must supply a truthful `per_run_max_cost` for pre-run hard
  cost guarantees
- No LLM provider calls (by design)
- GitHub-only release; not published to PyPI (unrelated PyPI name collision)
