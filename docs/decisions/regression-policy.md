# Regression policy

AgentBench never invents acceptable degradation.

A `RegressionPolicy` is a list of `MetricRule`s. Each rule names:

- metric
- direction
- absolute and/or relative threshold
- minimum sample size
- hard gate vs informational

Contradictory or duplicate rules for the same metric are rejected at construction. There is no silent last-rule-wins merge.

Directions must be parsed through `MetricDirection.parse`. Raw strings that are not exact enum members are rejected.

Classifications:

- `IMPROVED` — candidate moved in the better direction
- `UNCHANGED` — no change, or change within the allowed degradation
- `REGRESSED` — worsened beyond a threshold
- `INCONCLUSIVE` — not enough samples, or relative delta undefined
- `UNAVAILABLE` — metric missing on baseline or candidate

Hard-gate regressions make the CLI exit `5`. Informational rules never do.

A cost-bound guarantee breach (`budget_guarantee_breached`) makes `agentbench run` exit `6`, even if a hard gate also failed. The completed run and `experiment.json` remain on disk.
