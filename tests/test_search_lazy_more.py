from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_lazy_more_batches_shard_loads_until_progress_or_exhaustion() -> None:
    renderer = _read("scripts/render_site.py")
    assert "loaded >= 8" in renderer
    assert "nextMatches.length > currentMatches.length" in renderer
    assert "if (loaded >= 8) break;" in renderer


def test_smoke_accepts_exhaustion_when_no_more_entries() -> None:
    smoke = _read("tests/daily_vnext_public_smoke.mjs")
    assert "load more did not render additional entries or exhaust" in smoke
    assert "moreExhausted" in smoke
    assert "moreClicks < 12" in smoke
