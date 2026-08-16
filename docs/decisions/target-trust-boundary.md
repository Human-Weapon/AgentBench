# Target execution trust boundary

`CommandTarget` is a convenience for black-box programs the **caller already trusts** enough to run on this machine.

Contract:

- argv list only
- `shell=False` always
- explicit cwd / env
- no implicit secret loading
- bounded timeout
- stdout/stderr/exit/duration captured

A string argv is a configuration error, not a shell command.

This is not SkillGuard. AgentBench will not decide whether a skill is malicious. It will happily measure two SkillGuard versions against a security-test dataset if you give it one.

Output-root containment and workspace copies reduce accidents (path-traversal IDs, clobbering the template). They are not a sandbox.
