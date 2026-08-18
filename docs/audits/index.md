# AgentBench audits

| Round | Baseline | Verdict | Notes |
|---|---|---|---|
| 0 | `8cf79f34eec27de8c98b0cecc2b34bf298edd41c` | D — NOT RELEASE READY | Independent Codex audit |
| 1 | `f876419dd2b13a207a30a6a661bc1cc892d44e30` | remediating | See `remediation-round-1.md` |
| 1b | `f080f8c5fa46a11204d2db533a621d598324bb1d` | cost-bound honesty | measured cost is never clamped |
| 1c | `0ad5bfeed523c253669a2abb0ec4208df9194f3b` | CLI exit 6 | cost-bound breach is not success |
| 2 | second Codex audit of `0ad5bfeed` | D — NOT RELEASE READY | AB2-001..007 |
| 2b | `5d64b28482e8ff69864abb3b414c8f0b61a0f2f9` | remediating | See `remediation-round-2.md` |
| 3 | third Codex audit of `5d64b28` | D — NOT RELEASE READY | 6 residual P1s |
| 3b | this tree | remediating | See `remediation-round-3.md` |

No tag. No GitHub Release. No PyPI.
