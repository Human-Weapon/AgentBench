from __future__ import annotations

from pathlib import Path

from agentbench.workspace import (
    DirectoryCopyWorkspace,
    diff_snapshots,
    snapshot_tree,
    source_fingerprint,
)


def test_source_template_remains_unchanged(tmp_path: Path) -> None:
    template = tmp_path / "template"
    template.mkdir()
    seed = template / "seed.txt"
    seed.write_text("original", encoding="utf-8")
    before = source_fingerprint(template)
    provider = DirectoryCopyWorkspace(template)
    dest = tmp_path / "run-ws"
    provider.create(dest)
    (dest / "created.txt").write_text("new", encoding="utf-8")
    (dest / "seed.txt").write_text("changed", encoding="utf-8")
    provider.assert_source_unchanged()
    assert seed.read_text(encoding="utf-8") == "original"
    assert source_fingerprint(template) == before
    assert (dest / "created.txt").read_text(encoding="utf-8") == "new"


def test_file_diff_metrics(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "keep.txt").write_text("a", encoding="utf-8")
    (root / "gone.txt").write_text("b", encoding="utf-8")
    before = snapshot_tree(root)
    (root / "new.txt").write_text("c", encoding="utf-8")
    (root / "keep.txt").write_text("aa", encoding="utf-8")
    (root / "gone.txt").unlink()
    diff = diff_snapshots(before, snapshot_tree(root))
    assert diff.files_created == 1
    assert diff.files_deleted == 1
    assert diff.files_modified == 1
    assert "new.txt" in diff.created_paths
    assert "gone.txt" in diff.deleted_paths
    assert "keep.txt" in diff.modified_paths
    assert diff.bytes_changed > 0


def test_ignore_patterns(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / "__pycache__").mkdir(parents=True)
    (root / "__pycache__" / "x.pyc").write_text("cache", encoding="utf-8")
    (root / "real.py").write_text("print(1)", encoding="utf-8")
    snap = snapshot_tree(root)
    assert "real.py" in snap
    assert not any(p.startswith("__pycache__") for p in snap)
