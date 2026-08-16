# Optional ecosystem integrations

USEFUL ALONE — BETTER TOGETHER.

| Project | How AgentBench relates |
|---|---|
| PromptGraph | A variant label ("PromptGraph on/off"). AgentBench does not compile context. |
| AgentGear | `AgentGearEvidenceAdapter` maps a supplied evidence dict to `Telemetry`. No import of `agentgear` is required. |
| SkillGuard | May be the system under test. AgentBench does not audit skills. |
| ProjectKaizen | Consumes `summary.json` / `comparison.json` later. AgentBench never mutates a project from results. |

Sibling discovery uses `importlib.util.find_spec`. Missing siblings are `False` / `None`, never an import error at module load.
