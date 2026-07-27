from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts import release_gate


class ReleaseGateTests(unittest.TestCase):
    def test_blocks_duplicate_and_missing_ingestion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026-07-27.json").write_text(
                json.dumps([
                    {"doi": "10.1/x", "source": "rss", "source_type": "journal_article", "title": "A"},
                    {"doi": "10.1/x", "source": "rss", "source_type": "journal_article", "title": "A"},
                ]), encoding="utf-8"
            )
            (root / "quality.json").write_text(json.dumps({"totals": {"missing_abstract_today": 1}}), encoding="utf-8")
            (root / "ingestion.json").write_text(json.dumps({"new_today_missing_candidates": 2}), encoding="utf-8")
            (root / "formal.json").write_text(json.dumps({"suspected_missed_journals": 0}), encoding="utf-8")
            report = release_gate.run(Namespace(
                date="2026-07-27", daily_dir=root, quality_report=root / "quality.json",
                ingestion_audit=root / "ingestion.json", formal_audit=root / "formal.json",
                max_historical_days=14,
            ))
            self.assertFalse(report["ok"])
            self.assertEqual(report["warnings"][0]["code"], "missing_abstract_today")

    def test_allows_missing_abstract_when_discovery_integrity_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026-07-27.json").write_text(
                json.dumps([{"doi": "10.1/x", "source": "rss", "source_type": "journal_article", "title": "A"}]), encoding="utf-8"
            )
            for name, payload in (("quality.json", {"totals": {"missing_abstract_today": 1}}), ("ingestion.json", {"new_today_missing_candidates": 0}), ("formal.json", {"suspected_missed_journals": 0})):
                (root / name).write_text(json.dumps(payload), encoding="utf-8")
            report = release_gate.run(Namespace(
                date="2026-07-27", daily_dir=root, quality_report=root / "quality.json",
                ingestion_audit=root / "ingestion.json", formal_audit=root / "formal.json",
                max_historical_days=14,
            ))
            self.assertTrue(report["ok"])
            self.assertEqual(report["warnings"][0]["count"], 1)


if __name__ == "__main__":
    unittest.main()
