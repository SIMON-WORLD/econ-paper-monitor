from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from dedupe import collapse_daily_duplicates
from product_audit import audit, load_records


def journal_record(title: str, url: str, *, detected_at: str, official: str = "2026-07-01") -> dict:
    return {
        "id": f"url:{url}",
        "title": title,
        "authors": ["Author"],
        "journal": "世界经济",
        "journal_id": "journal-679eaa2a0c",
        "source": "cnki-rss" if "cnki" in url else "cn-official",
        "source_type": "journal",
        "url": url,
        "fields": ["chinese"],
        "detected_at": detected_at,
        "available_online": official,
        "date_confidence": "B",
    }


def test_cross_day_aliases_collapse_into_earliest_canonical_bucket(tmp_path: Path) -> None:
    daily = tmp_path / "daily"
    daily.mkdir()
    title = "打破数据孤岛：大数据管理局与上市公司异地投资"
    first = journal_record(title, "https://cnki.example/paper", detected_at="2026-07-01T01:00:00+08:00")
    official = journal_record(title, "https://journal.example/paper", detected_at="2026-07-02T01:00:00+08:00")
    (daily / "2026-07-01.json").write_text(json.dumps([first], ensure_ascii=False), encoding="utf-8")
    (daily / "2026-07-02.json").write_text(json.dumps([official], ensure_ascii=False), encoding="utf-8")

    assert collapse_daily_duplicates(daily) == 1

    kept = json.loads((daily / "2026-07-01.json").read_text(encoding="utf-8"))
    assert len(kept) == 1
    assert kept[0]["url"] == "https://journal.example/paper"
    assert json.loads((daily / "2026-07-02.json").read_text(encoding="utf-8")) == []


def test_full_history_audit_reports_integrity_errors(tmp_path: Path) -> None:
    daily = tmp_path / "daily"
    daily.mkdir()
    old = journal_record(
        "A valid research paper title long enough for identity matching",
        "https://journal.example/old",
        detected_at="2026-07-20T01:00:00+08:00",
        official="2023-01-19",
    )
    duplicate = dict(old, id="alias", url="https://journal.example/alias")
    bad_id = journal_record(
        "Another valid economics research paper",
        "https://journal.example/bad-id",
        detected_at="not-a-timestamp",
        official="2026-07-21",
    )
    bad_id["journal_id"] = "not-in-formal-scope"
    (daily / "2026-07-20.json").write_text(json.dumps([old, duplicate]), encoding="utf-8")
    (daily / "2026-07-21.json").write_text(json.dumps([bad_id]), encoding="utf-8")

    report = audit(load_records(daily), {"journal-679eaa2a0c"})

    assert report["totals"]["duplicates_by_url_or_doi"] == 1
    assert report["totals"]["historical_records_in_bucket"] == 2
    assert report["totals"]["malformed_first_seen"] == 1
    assert report["totals"]["invalid_journal_ids"] == 1
