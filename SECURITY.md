# Security Policy for AgentBench

## Reporting a vulnerability

If you discover a security issue, **do not open a public issue**. Contact the maintainers (address TBD once the repo is published) with:

- a description of the issue
- steps to reproduce
- affected versions
- any suggested fix

We will acknowledge receipt within 48 hours and work toward a coordinated disclosure.

## Threat model (be precise)

AgentBench executes **caller-configured commands**.

It is **NOT** a sandbox for untrusted programs.

- Commands are deliberately supplied by the caller (suite config or Python API).
- Default execution uses an argv list with `shell=False`. That reduces injection from string interpolation; it does not make a hostile binary safe.
- There is no shell mode in v0.1.0. A giant shell string is rejected.
- Callers should benchmark code they trust, or isolate the process externally (container, VM, separate user).
- Output-root and workspace containment is **defensive, best-effort filesystem handling**. It is not proof against a privileged local attacker swapping junctions/symlinks between every syscall.
- Do not put secrets in benchmark configs unless the target truly needs them. AgentBench does not load secret stores implicitly.
- AgentBench does **not** scan targets for malware. That job belongs to **SkillGuard**.
- AgentBench makes **no network calls** and requires **no API keys**.

## What AgentBench deliberately does NOT do

- model routing or strategy selection (AgentGear)
- skill/plugin security auditing (SkillGuard)
- context compilation (PromptGraph)
- automatic modification of the project under test (ProjectKaizen)

## Standalone guarantee

AgentBench must never require a sibling package to function. Optional adapters use `importlib.find_spec` and degrade if the sibling is absent.

## Priority

- **P0** — security / data loss / critical bugs: fix immediately
- **P1** — broken functionality: next release
- **P2+** — scheduled normally
