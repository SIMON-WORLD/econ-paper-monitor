from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from triage_source_health import categorize_error, triage  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestCategorizeError:
    def test_permanent_403(self):
        assert categorize_error("HTTP 403 Forbidden") == "permanently_unavailable"

    def test_permanent_418(self):
        assert categorize_error("HTTP 418 I am a teapot") == "permanently_unavailable"

    def test_permanent_captcha(self):
        assert categorize_error("Blocked by CAPTCHA challenge") == "permanently_unavailable"

    def test_permanent_cloudflare(self):
        assert categorize_error("Cloudflare protection blocked the request") == "permanently_unavailable"

    def test_permanent_404(self):
        assert categorize_error("HTTP 404 Not Found") == "permanently_unavailable"

    def test_permanent_410(self):
        assert categorize_error("HTTP 410 Gone") == "permanently_unavailable"

    def test_rate_limited_429(self):
        assert categorize_error("HTTP 429 Too Many Requests") == "rate_limited"

    def test_rate_limited_throttle(self):
        assert categorize_error("Request throttled, please wait") == "rate_limited"

    def test_rate_limited_503(self):
        assert categorize_error("503 Service Temporarily Unavailable") == "rate_limited"

    def test_page_structure_keyerror(self):
        assert categorize_error("KeyError: 'title' not found in response") == "page_structure_change"

    def test_page_structure_json_decode(self):
        assert categorize_error("JSONDecodeError: Expecting value") == "page_structure_change"

    def test_page_structure_selector(self):
        assert categorize_error("Selector not found: .article-title") == "page_structure_change"

    def test_transient_timeout(self):
        assert categorize_error("Connection timed out after 30 seconds") == "transient_network"

    def test_transient_connection_reset(self):
        assert categorize_error("Connection reset by peer") == "transient_network"

    def test_transient_dns(self):
        assert categorize_error("Temporary failure in name resolution") == "transient_network"

    def test_transient_ssl(self):
        assert categorize_error("SSL certificate verify failed") == "transient_network"

    def test_needs_investigation_unknown(self):
        assert categorize_error("Some unknown error message") == "needs_investigation"

    def test_needs_investigation_empty(self):
        assert categorize_error("") == "needs_investigation"


class TestTriageReport:
    def test_triage_combines_source_health_and_status(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        write_json(
            data_dir / "source_health.json",
            {
                "counts": {"degraded": 2, "healthy": 1},
                "degraded": [
                    {
                        "journal": "Journal A",
                        "journal_id": "j-a",
                        "coverage": "supplemental",
                        "failed_paths": [{"message": "HTTP 429 Too Many Requests"}],
                    },
                    {
                        "journal": "Journal B",
                        "journal_id": "j-b",
                        "coverage": "supplemental",
                        "failed_paths": [{"message": "KeyError: abstract"}],
                    },
                ],
            },
        )
        write_json(
            data_dir / "status.json",
            {
                "sources": {
                    "journal-c": {
                        "ok": False,
                        "last_error": "Connection timed out",
                    }
                }
            },
        )
        report = triage(data_dir)
        assert report["total_degraded"] == 2
        assert report["source_health_degraded_count"] == 2
        assert report["status_json"]["aligned"] is True
        assert report["status_json"]["degraded_source_failures"] == 1
        by_source = {entry["source"]: entry["category"] for entry in report["sources"]}
        assert by_source["Journal A"] == "rate_limited"
        assert by_source["Journal B"] == "page_structure_change"
        assert "journal-c" not in by_source
        status_failures = {entry["source"]: entry["category"] for entry in report["source_status_failures"]}
        assert status_failures["journal-c"] == "transient_network"

        written = json.loads((data_dir / "source_health_triage.json").read_text(encoding="utf-8"))
        assert written["total_degraded"] == 2

    def test_empty_health_returns_empty_report(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        write_json(data_dir / "source_health.json", {"degraded": [], "counts": {}})
        write_json(data_dir / "status.json", {"sources": {}})
        report = triage(data_dir)
        assert report["total_degraded"] == 0
        assert report["sources"] == []
        assert report["source_status_failures"] == []

    def test_degraded_journals_without_failed_paths_are_still_triaged(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        write_json(
            data_dir / "source_health.json",
            {
                "counts": {"degraded": 3, "healthy": 0},
                "degraded": [
                    {"journal": "Journal A", "journal_id": "j-a", "coverage": "supplemental", "level": "degraded"},
                    {"journal": "Journal B", "journal_id": "j-b", "coverage": "supplemental", "level": "degraded"},
                    {
                        "journal": "Journal C",
                        "journal_id": "j-c",
                        "coverage": "supplemental",
                        "failed_paths": [{"message": "HTTP 429 Too Many Requests"}],
                    },
                ],
            },
        )
        write_json(
            data_dir / "status.json",
            {
                "sources": {
                    "rss": {
                        "ok": False,
                        "last_error": "Journal B: 0 via configured; Journal C: timeout",
                    }
                }
            },
        )
        report = triage(data_dir)
        assert report["total_degraded"] == 3
        assert report["status_json"]["aligned"] is True
        by_source = {entry["source"]: entry for entry in report["sources"]}
        assert by_source["Journal A"]["category"] == "needs_investigation"
        assert by_source["Journal B"]["status_source"] == "rss"
        assert by_source["Journal C"]["category"] == "rate_limited"

    def test_alignment_flag_false_when_counts_differ(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        write_json(
            data_dir / "source_health.json",
            {
                "counts": {"degraded": 5, "healthy": 0},
                "degraded": [{"journal": "Journal A", "journal_id": "j-a"}],
            },
        )
        write_json(data_dir / "status.json", {"sources": {}})
        report = triage(data_dir)
        assert report["total_degraded"] == 1
        assert report["source_health_degraded_count"] == 5
        assert report["status_json"]["aligned"] is False
