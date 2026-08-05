"""Tests for the Semantic Scholar usage aggregation report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_semantic_scholar_usage import build_usage  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def make_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    write_json(
        data_dir / "metadata_provider_health.json",
        {
            "latest": {
                "candidates": 150,
                "checked_at": "2026-08-05T03:30:18-04:00",
                "providers": {
                    "semantic-scholar": {
                        "api_key_configured": True,
                        "attempts": 150,
                        "available": 100,
                        "statuses": {"not_found": 20, "rate_limited": 30},
                    }
                },
            },
            "runs": [
                {
                    "candidates": 150,
                    "checked_at": "2026-08-04T10:00:00+00:00",
                    "providers": {
                        "semantic-scholar": {
                            "api_key_configured": True,
                            "attempts": 150,
                            "available": 120,
                            "statuses": {"not_found": 25, "rate_limited": 5},
                        }
                    },
                },
                {
                    "candidates": 150,
                    "checked_at": "2026-08-03T22:00:00+00:00",
                    "providers": {
                        "semantic-scholar": {
                            "api_key_configured": False,
                            "attempts": 150,
                            "available": 90,
                            "statuses": {"not_found": 30, "rate_limited": 30},
                        }
                    },
                },
            ],
        },
    )
    write_json(
        data_dir / "semantic_scholar_keepalive.json",
        {
            "checked_at": "2026-08-05T03:30:20-04:00",
            "ok": True,
            "status_code": 200,
            "reason": "ok",
        },
    )
    return data_dir


def test_usage_aggregates_totals_and_days(tmp_path: Path) -> None:
    data_dir = make_data_dir(tmp_path)

    usage = build_usage(data_dir)

    assert usage["key_configured"] is True
    assert usage["total"]["attempts"] == 450
    assert usage["total"]["available"] == 310
    assert usage["total"]["rate_limited"] == 65
    assert usage["total"]["not_found"] == 75
    assert usage["total"]["runs"] == 3
    assert usage["last_used_at"] == "2026-08-05T03:30:18-04:00"
    assert usage["last_keepalive_ok"] is True
    assert usage["last_keepalive_reason"] == "ok"
    assert [row["date"] for row in usage["by_day"]] == ["2026-08-04", "2026-08-05"]
    assert usage["by_day"][0]["attempts"] == 300  # 08-03 22:00 UTC == Beijing 08-04
    assert usage["by_day"][0]["rate_limited"] == 35
    assert usage["by_day"][-1]["attempts"] == 150
    assert usage["by_day"][-1]["rate_limited"] == 30
    assert isinstance(usage["days_since_last_use"], int)


def test_usage_empty_health_is_honest(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    write_json(data_dir / "metadata_provider_health.json", {"runs": [], "latest": {}})

    usage = build_usage(data_dir)

    assert usage["total"]["attempts"] == 0
    assert usage["by_day"] == []
    assert usage["key_configured"] is False
    assert usage["days_since_last_use"] is None