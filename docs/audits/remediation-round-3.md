# AgentBench v0.1.0 — Codex audit remediation Round 3

Audited SHA: `5d64b28482e8ff69864abb3b414c8f0b61a0f2f9` (third independent
Codex audit, verdict D).

## P1

### AB2-002 residual — `hard_gate: null`
Omitted → default `false`. Present `true`/`false` valid. Present `null`
and every non-bool rejected. Same path for loader, `validate`, and `run`.

### AB3-001 — non-string mapping keys
`str(key)` collapsed `{1: "a", "1": "b"}`. Keys must already be strings
in `to_jsonable` and `deep_freeze`. Never stringify. Never last-win.

### AB3-002 — open config objects
Unknown target/evaluator/metric fields rejected. Falsey wrong types
(`budget: []`, `config: []`) no longer become `{}`.

### AB-R2-NEW-001 residual — constructor vs loader
`TargetResult(timed_out=0)` constructed then could not be reloaded.
Booleans are validated at construction.

### AB3-003 — persist repair
`details: []` / `files_created: false` are corrupt, not rewritten.

### AB3-004 — report write escape
`Path.write_text` bypassed ResultStore. Report now uses
`contained_filename` + `write_text`. Linked dest whose realpath leaves
the trusted root is `PathEscapeError`. Zero outside writes.

Residual: not a kernel-level race-free sandbox. Hard-link aliasing of
an existing trusted file is outside this threat model.
