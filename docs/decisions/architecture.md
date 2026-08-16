# Architecture

AgentBench is a measurement library. The public flow is:

```
suite + target + evaluators
        │
        ▼
 ExperimentRunner (sequential)
        │
        ├─ BudgetLedger.check_can_start
        ├─ DirectoryCopyWorkspace (optional)
        ├─ BenchmarkTarget.run
        ├─ Evaluator.evaluate
        ├─ ResultStore.write_run   (atomic, incremental)
        └─ aggregate / compare / report
```

Modules stay small. There is no God class. `ExperimentRunner` orchestrates; it does not parse configs, compute statistics, or render markdown.

## Status model

| Status | Meaning |
|---|---|
| SUCCESS | target completed with its own success criteria (typically exit 0) |
| FAILURE | target ran and failed — this is benchmark data |
| TIMEOUT | hard per-run timeout fired — benchmark data, not a crash |
| ERROR | infrastructure failure (spawn, containment, source mutation) |
| SKIPPED | not executed (budget or abort) |

A target can be `SUCCESS` while a validation command evaluator is `passed=False`. Those facts are stored separately.

## Execution order

v0.1.0 is sequential. Parallel execution is deferred: it is faster on paper and a concurrency defect factory in practice.
