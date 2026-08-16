"""Active release metadata must stay publication-ready."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/Human-Weapon/AgentBench"
FORBIDDEN = (
    "oss@hermes.local",
    "address TBD",
    "TBD once the repo is published",
)


def test_pyproject_author_and_repository_url() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "Human-Weapon"' in text
    assert REPO_URL in text
    for token in FORBIDDEN:
        assert token not in text


def test_security_md_has_no_stale_placeholders() -> None:
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    for token in FORBIDDEN:
        assert token not in text
    lowered = text.lower()
    assert "sandbox" in lowered
    assert "shell=false" in lowered
    assert "skillguard" in lowered
