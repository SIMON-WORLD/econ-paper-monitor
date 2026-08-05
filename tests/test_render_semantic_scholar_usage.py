"""Tests for the Semantic Scholar usage page renderer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from render_semantic_scholar_usage import render_usage  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def sample_usage() -> dict:
    return {
        "updated_at": "2026-08-05T12:00:00+00:00",
        "key_configured": True,
        "last_used_at": "2026-08-05T03:30:18-04:00",
        "last_keepalive_at": "2026-08-05T03:30:20-04:00",
        "last_keepalive_ok": True,
        "last_keepalive_reason": "ok",
        "days_since_last_use": 0,
        "total": {"attempts": 450, "available": 310, "not_found": 75, "rate_limited": 65, "skipped": 0, "http_error": 0, "runs": 3},
        "by_day": [
            {
                "date": "2026-08-04",
                "attempts": 300,
                "available": 210,
                "not_found": 55,
                "rate_limited": 35,
                "skipped": 0,
                "http_error": 0,
                "runs": 2,
            },
            {
                "date": "2026-08-05",
                "attempts": 150,
                "available": 100,
                "not_found": 20,
                "rate_limited": 30,
                "skipped": 0,
                "http_error": 0,
                "runs": 1,
            },
        ],
    }


def test_renders_usage_page(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    docs_dir = tmp_path / "docs"
    write_json(data_dir / "semantic_scholar_usage.json", sample_usage())

    out = render_usage(data_dir, docs_dir)

    assert out == docs_dir / "usage" / "index.html"
    html = out.read_text(encoding="utf-8")
    assert "Semantic Scholar API 用量" in html
    assert "450" in html and "310" in html and "65" in html
    assert "2026-08-05" in html
    assert "60 天" in html  # policy note
    assert "已配置" in html


def test_missing_usage_renders_placeholder(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    docs_dir = tmp_path / "docs"

    out = render_usage(data_dir, docs_dir)

    html = out.read_text(encoding="utf-8")
    assert "用量数据尚未生成" in html
    assert "Semantic Scholar API 用量" in html


def test_usage_values_are_escaped(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    docs_dir = tmp_path / "docs"
    usage = sample_usage()
    usage["updated_at"] = '<script>alert(1)</script>'
    usage["by_day"][0]["date"] = '<img src=x onerror=alert(1)>'
    write_json(data_dir / "semantic_scholar_usage.json", usage)

    html = render_usage(data_dir, docs_dir).read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html