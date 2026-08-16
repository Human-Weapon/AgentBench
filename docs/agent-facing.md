# Using AgentBench from an agent

This file is a skill-facing description. It is not a claim of compatibility with any particular agent-skill platform specification.

## When to use

Use AgentBench when you need **evidence** about two or more configurations:

- Did strategy A beat strategy B on this suite?
- Did version 0.2 regress vs 0.1?
- Did a fix hold without raising timeout rate?

Do not use AgentBench to pick a production model. Hand the report to the caller or to AgentGear.

## How to run

Prefer the Python API inside tests and the CLI for humans:

```
agentbench validate <suite.json>
agentbench run <suite.json> --output <dir>
agentbench compare <dir> --baseline <id>
agentbench report <dir>
```

Configs must use argv arrays. Never put a shell string in `target.argv` or `validation_command`.

## Honesty rules

- Missing cost/tokens stay unknown.
- Do not write "objectively better" when tradeoffs exist.
- Quote sample sizes.
- A flaky case is a first-class finding.
