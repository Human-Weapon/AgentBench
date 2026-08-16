# Statistics philosophy

Claim ≤ verified behavior.

AgentBench reports descriptive statistics and paired win rates. It does not claim that a difference is "significant".

If bootstrap confidence intervals are added later, they must be deterministic (seeded) and documented. Until then they do not exist, and reports must not pretend they do.

No scipy/numpy dependency in v0.1.0. `statistics` from the stdlib is enough.
