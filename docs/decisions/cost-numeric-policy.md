# Cost numeric policy

AgentBench accounts hard cost budgets with `decimal.Decimal`.

Each reservation and each measured cost is converted independently via
`Decimal(str(value))`. Reservations are summed in decimal space.

This exists so three caller-supplied `0.1` reservations against
`max_total_cost=0.3` are not rejected because IEEE-754 produced
`0.30000000000000004`.

It is **not** a wide epsilon:

- `measured > per_run_max_cost` still violates the cost-bound contract
  (`0.4000001` vs `0.4`).
- measured cost is never clamped to the reservation.
- UNKNOWN keeps the reservation committed and does not invent `0`.
