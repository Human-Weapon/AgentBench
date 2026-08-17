# AgentBench v0.1.0 — Codex audit remediation Round 2

Audited SHA: `0ad5bfeed523c253669a2abb0ec4208df9194f3b` (second independent
Codex audit, verdict D).

Reproduce P1s in a detached worktree of that SHA. Do not mutate the baseline.

## P1

### AB2-001 — CommandTarget stringified frozen payloads
`json.dumps(..., default=str)` turned `MappingProxyType` payloads into
`"mappingproxy({'n': 4})"`. The shipped example therefore ran 8
infrastructure-ish failures instead of 6 SUCCESS / 2 FAILURE.

Fix: one `to_jsonable()` boundary. Mappings → dict, sequences → list,
JSON scalars preserved. Arbitrary objects raise `ValidationError`. No
`default=str` on payload / persist / workspace dumps.

### AB2-002 — `hard_gate: "false"` became True
`bool("false")` is True. Validate now loads the same path as `run`
(`load_validated_config`) and rejects non-boolean gate fields, unknown
keys, and malformed pricing.

## P2

### AB2-003 — output-root junction replacement
Store the original realpath identity at construction. Re-check before
every write. A swapped junction/symlink is `PathEscapeError` with zero
outside artifacts.

### AB-007 remaining — nested persist schema
`telemetry=[]` (and other non-objects) is `CorruptResultError`, not
UNKNOWN. Missing/null telemetry remains empty UNKNOWN.

### AB-011 remaining — callable `None`
`PythonCallableTarget` returning `None` is `TargetExecutionError`.

### AB2-004 — pairing omitted seed
Pair key is `(case_id, repetition, seed)`. Duplicate keys raise.

### AB2-005 — float `0.1+0.1+0.1 > 0.3`
Internal ledger uses `Decimal`. See `docs/decisions/cost-numeric-policy.md`.

## P3

### AB2-007 — exact output cap
`N` bytes with cap `N` is not truncated. `N+1` is.

## Original partials

AB-009 / AB-010: unknown regression fields, raw enum parse, bool-as-int,
and nested rule objects are now rejected at `from_config` / `validate`.
Config-relative paths were already bound at load in Round 1.
