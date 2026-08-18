# AgentBench v0.1.0 — Codex audit remediation Round 4

Audited SHA: `59d3dfca48ae1fc28a0ae9550b56509fee189b51` (fourth independent
promotion audit, verdict C).

## Field classes

- REQUIRED — null invalid
- OPTIONAL ABSENT — omission allowed, explicit null invalid
- NULLABLE — explicit null is part of the schema (`str | None`, `workspace_diff`)

## P1

### AB4-001 — explicit null normalized
`_field_mapping` / `_field_str` treated `key not in raw or value is None`
as omission. Explicit null now raises `CorruptResultError` for
optional-absent fields (details, stdout, evaluations, path lists,
timestamps).

### AB4-002 — timestamps
Public constructor accepted `None` / ints. Loader turned null into `""`
and rejected numbers. Contract: `str`, empty or ISO-8601, at both ends.

## P2

### AB4-003 — paths and errors
`created_paths` accepted mappings/nulls. `error` / `error_message`
accepted arbitrary JSON. Now `tuple[str, ...]` and `str | None`.
