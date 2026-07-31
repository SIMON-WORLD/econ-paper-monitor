from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from reconcile_retry_queues import reconcile_retry_queue  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_retry_queue_reconciles_daily_seen_and_pending_records(tmp_path: Path) -> None:
    daily = {
        "title": "Canonical DOI paper",
        "journal": "Example Journal",
        "doi": "10.1234/example",
        "url": "https://doi.org/10.1234/example",
        "detail_key": "canonical-doi-paper-123456789abc",
    }
    seen = {
        "title": "Canonical Wiley title",
        "journal": "The World Economy",
        "url": "https://onlinelibrary.wiley.com/doi/10.1111/twec.70131",
        "detail_key": "canonical-wiley-title-123456789abc",
    }
    pending = {
        "title": "待归档中文论文",
        "journal": "经济研究",
        "url": "https://example.cn/#/detail?contentId=123",
        "detail_key": "pending-chinese-paper-123456789abc",
    }
    candidates = [
        dict(daily, retry_status="pending", stage="retry_reingestion"),
        {
            "title": seen["title"],
            "source": seen["journal"],
            "url": seen["url"] + "?af=R",
            "retry_status": "pending",
            "stage": "retry_reingestion",
        },
        dict(pending, retry_status="pending", stage="retry_reingestion"),
        {
            "title": "Still missing",
            "source": "Example Journal",
            "url": "https://example.test/still-missing",
            "retry_status": "pending",
            "stage": "retry_reingestion",
        },
    ]
    write_json(tmp_path / "daily" / "2026-07-31.json", [daily])
    write_json(tmp_path / "seen.json", {"papers": {"seen-key": seen}})
    write_json(tmp_path / "pending_date_records.json", [pending])
    write_json(tmp_path / "ingestion_retry_queue.json", {"records": candidates})
    write_json(tmp_path / "ingestion_exclusion_ledger.json", {"records": candidates})

    report = reconcile_retry_queue(tmp_path)

    assert report["pending_before"] == 4
    assert report["resolved_now"] == 3
    assert report["pending_after"] == 1
    queue = json.loads((tmp_path / "ingestion_retry_queue.json").read_text(encoding="utf-8"))
    assert [record["title"] for record in queue["records"]] == ["Still missing"]
    assert len(queue["resolved_records"]) == 3
    ledger = json.loads((tmp_path / "ingestion_exclusion_ledger.json").read_text(encoding="utf-8"))
    assert sum(record.get("retry_status") == "resolved" for record in ledger["records"]) == 3

    second = reconcile_retry_queue(tmp_path)
    assert second["resolved_now"] == 0
    assert second["pending_after"] == 1
    queue_second = json.loads((tmp_path / "ingestion_retry_queue.json").read_text(encoding="utf-8"))
    assert len(queue_second["resolved_records"]) == 3
