# Regression policy

AgentBench never invents acceptable degradation.

A `RegressionPolicy` is a list of `MetricRule`s. Each rule names:

- metric
- direction
- absolute and/or relative threshold
- minimum sample size
- hard gate vs informational

Contradictory rules (same metric, opposite directions) are rejected at construction.

Classifications:

- `IMPROVED` — candidate moved in the better direction
- `UNCHANGED` — no change, or change within the allowed degradation
- `REGRESSED` — worsened beyond a threshold
- `INCONCLUSIVE` — not enough samples, or relative delta undefined
- `UNAVAILABLE` — metric missing on baseline or candidate

Hard-gate regressions make the CLI exit `5`. Informational rules never do.
