# Remediation Round 1

Audited baseline: `8cf79f34eec27de8c98b0cecc2b34bf298edd41c`

Independent Codex verdict: D — NOT RELEASE READY.

Each finding below was reproduced against that SHA in a detached worktree
(`C:/Users/pokem/AppData/Local/Temp/agentbench-baseline-8cf79f3`) unless noted.

## AB-001 — P1 — hard cost budget

- Original: `BudgetLedger` added measured cost after the run. `None` set
  `cost_known=False` but did not consume budget, so UNKNOWN cost behaved as free.
- Reproduction: two variants, `max_total_cost=0.5`, both returned `cost=None`.
  Baseline invoked `['a', 'b']`.
- Root cause: no pre-run reservation; post-hoc accounting cannot enforce a hard cap.
- Regression: `tests/adversarial/test_remediation_round1.py` (`test_ab001_*`)
- Fix: `ExecutionBudget.max_total_cost` requires `per_run_max_cost`. Reserve
  before `target.run`. UNKNOWN keeps the reservation. Measured 0 stays 0.
  Reconciliation cannot go negative. Measured cost is never clamped to the
  reservation. If measured exceeds the bound, `cost_bound_violated` is set
  and further runs stop.
- Remaining: callers must supply a truthful per-run upper bound. AgentBench
  cannot invent one. If measured cost exceeds the reservation, the actual
  spend is recorded (`cost_bound_violated`); it is **not** clamped. The hard
  pre-execution guarantee is then breached and further runs stop.

## AB-002 — P1 — case workspace immutability

- Original: suite-level templates were checked after the target; case-level
  templates were only checked before.
- Reproduction: target wrote through `case.workspace_template` to the original
  tree. Baseline completed with `source=mutated` and no `SourceMutationError`.
- Root cause: split code path.
- Regression: `test_ab002_case_workspace_source_unchanged`,
  `test_ab002_mutating_original_template_is_detected`
- Fix: one workspace path. Case templates construct `DirectoryCopyWorkspace`
  and always `assert_source_unchanged()` after the target.

## AB-003 — P1 — timeout children

- Original: `subprocess.run(..., timeout=)` kills only the parent.
- Reproduction: baseline used that API. A parent/child sleep fixture is now
  required on Windows and Ubuntu CI.
- Root cause: no process group / tree kill.
- Regression: `test_ab003_timeout_kills_child_process`
- Fix: `process.run_bounded` starts a new process group (POSIX session /
  Windows `CREATE_NEW_PROCESS_GROUP`) and kills the tree (`killpg` /
  `taskkill /T`). Status remains `TIMEOUT`.
- Remaining: not a sandbox; only the spawned tree is targeted.

## AB-004 — P1 — output reuse

- Original: a second experiment in the same directory mixed run JSON.
- Reproduction: baseline invoked the target twice (`invoked=[1, 1]`).
- Root cause: `ResultStore` always accepted an existing root.
- Regression: `test_ab004_reuse_of_output_rejected`, `test_ab004_empty_dir_allowed`
- Fix: `assert_unused_output` refuses `experiment.json`, `summary.json`,
  `comparison.json`, `report.md`, or any `runs/*.json`. Empty dirs allowed.
  No silent delete, no silent merge.

## AB-005 — P1 — synthetic SKIPPED records

- Original: budget stops wrote `RunResult(status=SKIPPED)` and aggregated them.
- Reproduction: `max_runs=2` of 3 planned → `runs=3 skipped=1`.
- Root cause: unscheduled items treated as physical runs.
- Regression: `test_ab005_unscheduled_not_in_metrics`
- Fix: do not persist unscheduled items. Outcome carries `planned_runs`,
  `executed_runs`, `not_scheduled`. Aggregation sees only physical runs.

## AB-006 — P2 — active total duration

- Original: total duration was checked only between runs.
- Fix: effective timeout is `min(per_run_timeout, remaining_total)` using
  monotonic time. Zero remaining does not start a target.
- Regression: `test_ab006_total_duration_caps_active_run`

## AB-007 — P2 — nested schema

- Original: top-level keys were required; nested bools/`or 0` defaults hid defects.
- Fix: `Telemetry`/`TargetResult` constructors validate nested numbers; load
  wraps failures as `CorruptResultError`; `duration_seconds` no longer uses
  falsy `or 0.0`.
- Regression: `test_ab007_*`

## AB-008 — P2 — shallow freeze

- Original: `_freeze_map` was a shallow `dict()`.
- Fix: `deep_freeze` via `MappingProxyType` + tuples.
- Regression: `test_ab008_nested_immutability`

## AB-009 — P2 — config typos / relative paths

- Original: unknown keys ignored (`repetitons` silently defaulted). Relative
  workspace paths resolved against CWD.
- Fix: strict known-key sets. Paths bind to the config file directory.
- Regression: `test_ab009_*`

## AB-010 — P2 — regression rules / enums

- Original: duplicate same-direction rules were allowed; last rule won.
- Fix: any duplicate metric rule is rejected. `MetricDirection.parse` is the
  only public string constructor.
- Regression: `test_ab010_duplicate_and_raw_enum`

## AB-011 — P2 — invalid telemetry / targets

- Original: bad telemetry became empty `Telemetry()`; a string return became
  SUCCESS stdout.
- Fix: invalid telemetry raises; invalid callable returns raise
  `TargetExecutionError`. Runner also type-checks the target object.
- Regression: `test_ab011_*`

## AB-012 — P2 — nested NaN

- Original: Python `json` accepted `NaN`/`Infinity`.
- Fix: `parse_constant` + recursive `reject_nonfinite_tree`; dumps use
  `allow_nan=False`.
- Regression: `test_ab012_nan_in_config_rejected`

## AB-013 — P2 — junction / symlink escape

- Original: `copytree` could follow a junction/symlink out of the template.
- Fix: reject escaping reparse points / symlinks at provider construction;
  copy with `symlinks=True`.
- Regression: `test_ab013_escaping_link_rejected` (real junction on Windows,
  real symlink on POSIX).

## AB-014 — P2 — global `--json`

- Original: subparser `--json` default `False` overwrote a parent `--json`.
- Fix: subparser uses `default=argparse.SUPPRESS`.
- Regression: `test_ab014_global_json_before_subcommand`

## AB-015 — P3 — unbounded capture

- Original: `subprocess.run(capture_output=True)` held all output; a cap
  without drain can deadlock.
- Fix: threaded readers with byte caps that keep draining after the cap.
- Regression: `test_ab015_stdout_bounded`, `test_ab015_bool_limit_rejected`

## Self-adversarial notes

- AB-002 copy-only mutation is *not* a source mutation (correct). The real
  defect is mutating the original template path; that is now a hard error.
- Process-tree tests must use a real grandchild, not mocks.
- Cost reservation must happen *before* `mark_started`.
