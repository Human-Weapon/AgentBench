# Workspace isolation

`DirectoryCopyWorkspace` copies a template into a unique per-run directory.

Invariants:

1. The template is fingerprinted (SHA-256 over relative paths + content hashes).
2. The target receives the copy.
3. After the run, the template fingerprint must match. Divergence raises `SourceMutationError`.
4. File diffs are computed on the copy only.

Ignore patterns drop `.git`, `__pycache__`, `.venv`, caches. This is not a Git replacement.

Suite-level and case-level templates share the same path: fingerprint, isolated copy, post-run verification.

A symlink or Windows junction that resolves outside the template is rejected. `copytree(..., symlinks=True)` does not follow escaping links.

Relative `workspace_template` paths in a config file are bound to the **config file directory**, not the process CWD.
