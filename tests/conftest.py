# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
NETTIMOTO_DIR = FIXTURES_DIR / "nettimoto"
FORUM_DIR = FIXTURES_DIR / "forum"


def load_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")
