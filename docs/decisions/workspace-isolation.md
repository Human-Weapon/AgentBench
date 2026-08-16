# Workspace isolation

`DirectoryCopyWorkspace` copies a template into a unique per-run directory.

Invariants:

1. The template is fingerprinted (SHA-256 over relative paths + content hashes).
2. The target receives the copy.
3. After the run, the template fingerprint must match. Divergence raises `SourceMutationError`.
4. File diffs are computed on the copy only.

Ignore patterns drop `.git`, `__pycache__`, `.venv`, caches. This is not a Git replacement.
