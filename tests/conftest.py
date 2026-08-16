from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "fixtures" / "scripts"


@pytest.fixture
def scripts() -> Path:
    return SCRIPTS
