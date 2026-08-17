# AgentBench

Objective benchmarking and regression evaluation for AI agents, prompts, skills, models, and execution strategies.

**USEFUL ALONE — BETTER TOGETHER**

AgentBench answers one question:

> Which configuration performed better, **by measurable evidence**?

## What AgentBench is

AgentBench is a standalone measurement harness. It owns:

- benchmark suites, cases, and variants
- repeated experiments with a deterministic run ID
- isolated workspaces
- safe subprocess targets (`argv` lists, never `shell=True`)
- telemetry collection without inventing missing values
- statistical summaries (sample size always reported)
- baseline vs candidate comparison
- caller-defined regression gates
- machine-readable JSON results and an honest markdown report

## What AgentBench is NOT

AgentBench does **not**:

- choose which model, agent, or strategy to use in production (AgentGear)
- compile or budget context (PromptGraph)
- audit skills for malice (SkillGuard)
- rewrite a project from the evidence (ProjectKaizen)
- call any LLM provider or require API keys
- pretend statistical significance it did not compute
- invent vendor pricing
- treat missing cost/tokens/latency as zero

Variants are opaque metadata. Names such as Luna, Terra, or Claude may appear in examples. They never affect scoring.

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"

agentbench validate examples/suite.json
agentbench run examples/suite.json --output .agentbench-out
agentbench compare .agentbench-out --baseline fast-cheap
agentbench report .agentbench-out
```

The sample suite is fully local and deterministic. It compares a fast cheap heuristic against a slower accurate script. No network.

## Python API

```python
from agentbench import (
    BenchmarkCase,
    BenchmarkSuite,
    CommandTarget,
    ExecutionBudget,
    ExperimentRunner,
    ExperimentSpec,
    Variant,
    compare,
    generate_report,
)

suite = BenchmarkSuite(
    id="demo",
    name="demo",
    cases=(BenchmarkCase(id="even", name="even", payload={"n": 4}),),
    variants=(Variant(id="fast", name="fast"), Variant(id="slow", name="slow")),
    repetitions=2,
    seed=42,
    budget=ExecutionBudget(max_runs=8, per_run_timeout_seconds=10),
    baseline_variant_id="fast",
)
result = ExperimentRunner().run(
    ExperimentSpec(suite=suite, target=target, output_root="out")
)
comparison = compare(result.runs, baseline="fast")
print(generate_report(result, comparison=comparison))
```

## CLI

| Command | Purpose |
|---|---|
| `agentbench validate <suite>` | Load and validate a suite/config |
| `agentbench run <suite> -o DIR` | Execute sequentially and persist results |
| `agentbench compare DIR --baseline ID` | Baseline vs candidates |
| `agentbench report DIR` | Write `report.md` |
| `agentbench status` | Standalone / sibling detection |

`--json` selects machine-readable stdout. Ordinary config errors print `error: …` on stderr, use a stable non-zero exit code, and do **not** dump a traceback. `--debug` enables tracebacks.

CLI exit codes:

| Code | Meaning |
|---|---|
| 0 | command completed; cost-bound guarantee held; no failed hard regression gate |
| 1 | domain / config error |
| 2 | argparse usage error |
| 3 | budget would be exceeded before a run starts (API / pre-run) |
| 4 | corrupt persisted result |
| 5 | regression hard gate failed |
| 6 | caller-supplied `per_run_max_cost` was exceeded (`CostBoundViolationError`) |

If both a cost-bound breach and a hard-gate failure apply, the CLI returns **6**. The Python API still returns a structured `ExperimentOutcome` and does not raise after persisting the run.

## Suite format

JSON always works (stdlib). YAML works only if PyYAML is installed (`pip install agentbench[yaml]`). YAML is not a hard dependency.

A config describes **data and argv lists**. It never contains `eval`, `exec`, or shell strings.

See [`examples/suite.json`](examples/suite.json).

## Variants

A variant is **what is being compared**: a model name, a reasoning setting, PromptGraph on/off, 1 agent vs 3, version 0.1 vs 0.2.

AgentBench records the label and the measurements. It does not interpret "high reasoning is smarter".

## Metrics

Every metric has an explicit direction:

- `HIGHER_IS_BETTER` (success rate, tests passed)
- `LOWER_IS_BETTER` (latency, cost, tokens)

Missing measurements stay `null` / `None` (UNKNOWN). Zero means "we measured zero".

Cost is recorded only when:

1. the target reports it, or
2. the caller supplies an explicit `pricing` block with token rates.

There is no hardcoded OpenAI/Anthropic price table.

A weighted composite score exists only when every component has a declared range, direction, and weight. AgentBench will not silently average success rate with tokens.

## Comparison and regression gates

Comparison reports baseline value, candidate value, absolute delta, relative delta (when the baseline is non-zero), direction, and a classification:

`IMPROVED` · `UNCHANGED` · `REGRESSED` · `INCONCLUSIVE` · `UNAVAILABLE`

Thresholds are **caller-defined**. AgentBench does not invent acceptable degradation.

Insufficient samples, a zero baseline on a relative rule, or a missing metric produce `INCONCLUSIVE` / `UNAVAILABLE` — not a fake improvement.

Paired win rate is computed on matching `(case, repetition)` pairs.

Flaky case/variant pairs (mixed outcomes across repetitions) are listed explicitly. A 50% success rate does not hide flip-flops.

## Workspaces

`DirectoryCopyWorkspace` copies a template into a per-run directory. The target mutates the **copy**. The template is hashed before and after; mutation of the source is an error.

Filesystem diffs record created / modified / deleted files (with optional byte change). `.git`, `__pycache__`, `.venv`, and similar cache dirs are ignored.

## Targets

- `CommandTarget(argv)` — black-box process, `shell=False`, bounded timeout, captured stdout/stderr/exit/duration
- `PythonCallableTarget(fn)` — in-process deterministic adapter for tests

There is no shell mode in v0.1.0. A string argv is rejected.

On timeout AgentBench terminates the **process tree** (parent and descendants), status is `TIMEOUT` (not a generic `FAILURE`), and captured output is preserved up to the configured byte caps (`max_stdout_bytes` / `max_stderr_bytes`, default 1 MiB). Truncation is recorded in `artifacts`.

`--json` may appear before or after the subcommand. Both forms emit JSON only on stdout.

A target `FAILURE` is benchmark **data**. An infrastructure `ERROR` is distinguishable and may abort the rest of the experiment.

## Budgets

Hard limits, checked before a run starts:

| Limit | Semantics |
|---|---|
| `max_runs=N` | N physical runs allowed; N+1 is not scheduled |
| `max_runs=0` | nothing runs |
| `per_run_timeout_seconds` | per-run subprocess bound |
| `max_total_duration_seconds` | monotonic wall-clock cap; the active run timeout is `min(per_run, remaining)` |
| `max_total_cost` | hard only with `per_run_max_cost` reservation **before** the target runs |
| `per_run_max_cost` | pre-run upper bound reserved against `max_total_cost` |
| `max_failures` | stop scheduling after N target failures |

UNKNOWN cost is never treated as 0. If `max_total_cost` is set without `per_run_max_cost`, configuration is rejected: a hard pre-execution cap cannot be enforced after the fact. A reserved run whose measured cost is unknown keeps the reservation committed. Measured zero remains zero.

`per_run_max_cost` is a **caller-supplied** pre-run upper bound. The hard pre-execution guarantee holds only while those bounds are truthful. If a target later reports a measured (or pricing-estimated) cost **greater** than the reservation, AgentBench:

1. records the **actual** measured cost (never clamps it to the reservation);
2. sets `cost_bound_violated` / `budget_guarantee_breached`;
3. stops scheduling further runs;
4. does **not** claim the hard cost cap was successfully enforced.

That is a `CostBoundViolationError` contract: money already spent cannot be unspent.

Unscheduled budget items are **not** written as `RunResult` records. `planned_runs` / `executed_runs` / `not_scheduled` live on the experiment outcome.

Reusing an output directory that already contains AgentBench artifacts is rejected. Empty directories are allowed. Nothing is deleted.

Negatives, `True`/`False`, `NaN`, and `±Infinity` are rejected at construction.

## Persistence

Results live under an explicit output root:

```
out/
  experiment.json
  summary.json
  comparison.json
  report.md
  runs/<run-id>.json
```

`schema_version` is `1`. Each finished run is written atomically before the next starts, so a crash on run 50 does not erase run 49. Corrupt JSON is quarantined and raises `CorruptResultError`. It is never treated as an empty successful benchmark.

Output containment is **defensive filesystem handling**, not a sandbox against a privileged local attacker.

## Statistics philosophy

v0.1.0 reports sample count, mean/median/min/max/stdev, p50/p95 (linear interpolation, Hyndman & Fan type 7), deltas, and paired win rate.

It does **not** emit p-values or confidence intervals. A single sample is not a meaningful p95; the summary flags that.

## Optional integrations

AgentBench imports none of its siblings at module load.

| Sibling | Relationship |
|---|---|
| PromptGraph | represented as a variant (enabled/disabled). Not imported. |
| AgentGear | `AgentGearEvidenceAdapter` converts supplied evidence dicts into telemetry. No hard dependency. |
| SkillGuard | may be the *subject* of a benchmark; AgentBench does not scan malware. |
| ProjectKaizen | may consume `summary.json` / `comparison.json`. AgentBench never writes back into a project. |

`agentbench status` shows which siblings happen to be installed.

## Security / trust boundary

AgentBench executes **caller-configured** commands. It is not a sandbox for untrusted programs. See [SECURITY.md](SECURITY.md).

## Limitations (v0.1.0)

- Sequential execution only (no parallel worker pool)
- No web dashboard, database, or cloud service
- No LLM provider SDKs
- No automatic model router
- No security sandbox
- Percentile with `n=1` is the sample itself and is flagged
- No bootstrap confidence intervals
- macOS is **not verified** in CI
- Output containment is best-effort, not privileged-attacker proof

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/ tests/
ruff format --check src/ tests/
python -m build
```

Requires Python 3.10–3.12. Runtime dependency: **none** (stdlib only).

## License

MIT. See [LICENSE](LICENSE).

## Status

v0.1.0 is an **unreleased release candidate**. Do not treat it as audit-approved until an independent adversarial review lands. There is no `v0.1.0` git tag yet.
