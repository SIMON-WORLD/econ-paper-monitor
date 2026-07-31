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
        assert report["total_degraded"] == 3
        by_source = {entry["source"]: entry["category"] for entry in report["sources"]}
        assert by_source["Journal A"] == "rate_limited"
        assert by_source["Journal B"] == "page_structure_change"
        assert by_source["journal-c"] == "transient_network"

        written = json.loads((data_dir / "source_health_triage.json").read_text(encoding="utf-8"))
        assert written["total_degraded"] == 3

    def test_empty_health_returns_empty_report(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        write_json(data_dir / "source_health.json", {"degraded": [], "counts": {}})
        write_json(data_dir / "status.json", {"sources": {}})
        report = triage(data_dir)
        assert report["total_degraded"] == 0
        assert report["sources"] == []
