from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clean_nonpaper_records import clean_nonpaper_records  # noqa: E402


def test_confirmed_nonpapers_are_removed_and_recorded_in_ledger(tmp_path: Path) -> None:
    daily_dir = tmp_path / "daily"
    daily_dir.mkdir()
    records = [
        {
            "id": "annual",
            "title": "<i>Review of Economics and Statistics</i> 2026 Annual Report",
            "journal": "Review of Economics and Statistics",
            "url": "https://doi.org/10.1162/rest.e.1731",
        },
        {
            "id": "book-series",
            "title": "经济管理出版社重点系列书",
            "journal": "中国工业经济",
            "url": "https://example.cn/book-series",
        },
        {
            "id": "paper",
            "title": "A genuine economics research paper",
            "journal": "Example Journal",
            "url": "https://example.test/paper",
        },
    ]
    (daily_dir / "2026-07-31.json").write_text(json.dumps(records), encoding="utf-8")
    (tmp_path / "seen.json").write_text(
        json.dumps({"papers": {record["id"]: record for record in records}}), encoding="utf-8"
    )
    (tmp_path / "ingestion_exclusion_ledger.json").write_text('{"records": []}', encoding="utf-8")

    report = clean_nonpaper_records(
        daily_dir,
        tmp_path / "seen.json",
        tmp_path / "ingestion_exclusion_ledger.json",
    )

    assert report == {"daily": 2, "seen": 2, "ledger_added": 2}
    daily = json.loads((daily_dir / "2026-07-31.json").read_text(encoding="utf-8"))
    assert [record["id"] for record in daily] == ["paper"]
    seen = json.loads((tmp_path / "seen.json").read_text(encoding="utf-8"))["papers"]
    assert list(seen) == ["paper"]
    ledger = json.loads((tmp_path / "ingestion_exclusion_ledger.json").read_text(encoding="utf-8"))
    assert len(ledger["records"]) == 2
    assert all(record["exclusion_status"] == "confirmed_nonpaper" for record in ledger["records"])
