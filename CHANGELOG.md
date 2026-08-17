# Changelog

All notable changes to AgentBench are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 0.1.0 release candidate

First functional release candidate. **Not tagged.** Independent adversarial
audit of `8cf79f3` returned D. This tree is Remediation Round 1.

### Remediation Round 1

- Hard cost budget now requires a pre-run `per_run_max_cost` reservation.
  UNKNOWN cost is never treated as free.
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
- No confidence intervals
- macOS CI not configured
- Output containment is defensive, not a privileged-attacker sandbox
- No LLM provider calls (by design)
