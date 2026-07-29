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
    def write_supporting_reports(self, root: Path, *, unavailable: int = 0, raw_artifacts: int = 1) -> None:
        (root / "quality.json").write_text(json.dumps({"totals": {}}), encoding="utf-8")
        (root / "ingestion.json").write_text(json.dumps({
            "new_today_missing_candidates": 0,
            "raw_artifact_count": raw_artifacts,
        }), encoding="utf-8")
        (root / "formal.json").write_text(json.dumps({"suspected_missed_journals": 0}), encoding="utf-8")
        (root / "source.json").write_text(json.dumps({
            "checked_at": "2026-07-27T12:00:00+00:00",
            "counts": {"degraded": 0, "unavailable": unavailable, "stale": 0},
            "coverage_counts": {"crossref_only": 0},
        }), encoding="utf-8")

    def run_gate(self, root: Path):
        return release_gate.run(Namespace(
            date="2026-07-27", daily_dir=root, quality_report=root / "quality.json",
            ingestion_audit=root / "ingestion.json", formal_audit=root / "formal.json",
            source_health=root / "source.json", max_historical_days=14,
        ))

    def test_valid_empty_canonical_day_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026-07-27.json").write_text("[]", encoding="utf-8")
            self.write_supporting_reports(root)
            self.assertTrue(self.run_gate(root)["ok"])

    def test_missing_and_malformed_canonical_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_supporting_reports(root)
            missing = self.run_gate(root)
            self.assertIn("canonical_daily_missing", {item["code"] for item in missing["failures"]})
            (root / "2026-07-27.json").write_text('{"not": "a list"}', encoding="utf-8")
            malformed = self.run_gate(root)
            self.assertIn("canonical_daily_invalid", {item["code"] for item in malformed["failures"]})

    def test_empty_fetch_is_explicit_warning_but_valid_zero_day_remains_legal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026-07-27.json").write_text("[]", encoding="utf-8")
            self.write_supporting_reports(root, raw_artifacts=0)
            report = self.run_gate(root)
            self.assertTrue(report["ok"])
            self.assertIn("raw_fetch_empty", {item["code"] for item in report["warnings"]})

    def test_one_or_many_source_failures_are_blocking(self) -> None:
        for unavailable in (1, 4):
            with self.subTest(unavailable=unavailable), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "2026-07-27.json").write_text("[]", encoding="utf-8")
                self.write_supporting_reports(root, unavailable=unavailable)
                report = self.run_gate(root)
                failure = next(item for item in report["failures"] if item["code"] == "formal_sources_unavailable")
                self.assertEqual(failure["count"], unavailable)

    def test_reappearing_title_alias_is_blocked_as_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            title = "A sufficiently long paper title for canonical identity"
            records = [
                {"id": "a", "title": title, "journal": "Test Journal", "source": "rss", "source_type": "journal", "url": "https://one.example"},
                {"id": "b", "title": title, "journal": "Test Journal", "source": "crossref", "source_type": "journal", "url": "https://two.example"},
            ]
            (root / "2026-07-27.json").write_text(json.dumps(records), encoding="utf-8")
            self.write_supporting_reports(root)
            report = self.run_gate(root)
            self.assertIn("duplicate_public_records", {item["code"] for item in report["failures"]})

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
            (root / "source.json").write_text(json.dumps({"checked_at": "2026-07-27T12:00:00+00:00", "counts": {"degraded": 1, "unavailable": 0, "stale": 0}, "coverage_counts": {"crossref_only": 1}}), encoding="utf-8")
            report = release_gate.run(Namespace(
                date="2026-07-27", daily_dir=root, quality_report=root / "quality.json",
                ingestion_audit=root / "ingestion.json", formal_audit=root / "formal.json",
                source_health=root / "source.json",
                max_historical_days=14,
            ))
            self.assertFalse(report["ok"])
            self.assertIn("missing_abstract_today", {item["code"] for item in report["warnings"]})

    def test_allows_missing_abstract_when_discovery_integrity_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026-07-27.json").write_text(
                json.dumps([{"doi": "10.1/x", "source": "rss", "source_type": "journal_article", "title": "A"}]), encoding="utf-8"
            )
            for name, payload in (("quality.json", {"totals": {"missing_abstract_today": 1}}), ("ingestion.json", {"new_today_missing_candidates": 0}), ("formal.json", {"suspected_missed_journals": 0})):
                (root / name).write_text(json.dumps(payload), encoding="utf-8")
            (root / "source.json").write_text(json.dumps({"checked_at": "2026-07-27T12:00:00+00:00", "counts": {"degraded": 0, "unavailable": 0, "stale": 0}, "coverage_counts": {"crossref_only": 0}}), encoding="utf-8")
            report = release_gate.run(Namespace(
                date="2026-07-27", daily_dir=root, quality_report=root / "quality.json",
                ingestion_audit=root / "ingestion.json", formal_audit=root / "formal.json",
                source_health=root / "source.json",
                max_historical_days=14,
            ))
            self.assertTrue(report["ok"])
            self.assertIn("missing_abstract_today", {item["code"] for item in report["warnings"]})

    def test_labels_crossref_plus_recall_separately_from_single_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026-07-27.json").write_text(
                json.dumps([{"doi": "10.1/x", "source": "rss", "source_type": "journal_article", "title": "A"}]), encoding="utf-8"
            )
            for name, payload in (("quality.json", {"totals": {}}), ("ingestion.json", {"new_today_missing_candidates": 0}), ("formal.json", {"suspected_missed_journals": 0})):
                (root / name).write_text(json.dumps(payload), encoding="utf-8")
            (root / "source.json").write_text(json.dumps({
                "checked_at": "2026-07-27T12:00:00+00:00",
                "counts": {"degraded": 1, "unavailable": 0, "stale": 0},
                "coverage_counts": {"crossref_only": 0, "supplemental": 1},
            }), encoding="utf-8")
            report = release_gate.run(Namespace(
                date="2026-07-27", daily_dir=root, quality_report=root / "quality.json",
                ingestion_audit=root / "ingestion.json", formal_audit=root / "formal.json",
                source_health=root / "source.json", max_historical_days=14,
            ))
            codes = {item["code"] for item in report["warnings"]}
            self.assertIn("formal_sources_crossref_plus_recall", codes)
            self.assertNotIn("formal_sources_single_path", codes)

    def test_blocks_when_source_health_report_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026-07-27.json").write_text(
                json.dumps([{"doi": "10.1/x", "source": "rss", "source_type": "journal_article", "title": "A"}]), encoding="utf-8"
            )
            for name, payload in (("quality.json", {"totals": {}}), ("ingestion.json", {"new_today_missing_candidates": 0}), ("formal.json", {"suspected_missed_journals": 0})):
                (root / name).write_text(json.dumps(payload), encoding="utf-8")
            report = release_gate.run(Namespace(
                date="2026-07-27", daily_dir=root, quality_report=root / "quality.json",
                ingestion_audit=root / "ingestion.json", formal_audit=root / "formal.json",
                source_health=root / "missing-source.json", max_historical_days=14,
            ))
            self.assertFalse(report["ok"])
            self.assertIn("formal_source_health_missing_or_invalid", {item["code"] for item in report["failures"]})


if __name__ == "__main__":
    unittest.main()
