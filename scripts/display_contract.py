"""Shared display-layer contracts for public paper titles."""
from __future__ import annotations

from typing import Any


def display_titles(record: dict[str, Any]) -> tuple[str, str]:
    """Return (primary, secondary) titles for every non-Classic surface."""
    english = str(record.get("title") or record.get("title_en") or "").strip()
    chinese = str(record.get("title_zh") or "").strip()
    if chinese and chinese.casefold() != english.casefold():
        return chinese, english
    return english, ""
