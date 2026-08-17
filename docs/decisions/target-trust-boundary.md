# Target execution trust boundary

`CommandTarget` is a convenience for black-box programs the **caller already trusts** enough to run on this machine.

Contract:

- argv list only
- `shell=False` always
- explicit cwd / env
- no implicit secret loading
- bounded timeout
- process-tree termination on timeout
- stdout/stderr/exit/duration captured with explicit byte caps
- truncation flagged when a cap is hit (the child is still drained to avoid pipe deadlock)

A string argv is a configuration error, not a shell command.

This is not SkillGuard. AgentBench will not decide whether a skill is malicious. It will happily measure two SkillGuard versions against a security-test dataset if you give it one.

Output-root containment and workspace copies reduce accidents (path-traversal IDs, clobbering the template). They are not a sandbox.
