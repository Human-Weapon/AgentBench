# Metric semantics

- Direction is explicit per metric. Nothing defaults to "higher is better".
- `None` means UNKNOWN. `0` means measured zero. These are not interchangeable.
- Cost is never invented from vendor price tables. A `PricingConfig` supplied by the caller may estimate from tokens.
- Relative delta is `(candidate - baseline) / |baseline|`. If baseline is 0, relative delta is unavailable.
- p50/p95 use linear interpolation (Hyndman & Fan type 7). `n` is always published. `n < 2` sets `percentile_meaningful=False`.
- v0.1.0 does not compute confidence intervals or p-values.
- Composite scores require explicit normalization ranges, directions, and weights. Silent averaging of success + tokens + latency is rejected.
