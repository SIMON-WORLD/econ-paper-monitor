"""Tests for source health triage categorization."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from triage_source_health import categorize_error, triage_source


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


class TestTriageSource:
    def test_healthy_source(self):
        info = {"ok": True, "last_success": "2026-07-01T00:00:00"}
        result = triage_source("test-source", info)
        assert result["category"] == "healthy"

    def test_degraded_source(self):
        info = {"ok": False, "last_error": "HTTP 403 Forbidden", "consecutive_failures": 3}
        result = triage_source("test-source", info)
        assert result["category"] == "permanently_unavailable"
        assert result["consecutive_failures"] == 3

    def test_rate_limited_source(self):
        info = {"ok": False, "last_error": "HTTP 429 Too Many Requests", "consecutive_failures": 5}
        result = triage_source("test-source", info)
        assert result["category"] == "rate_limited"

    def test_page_structure_source(self):
        info = {"ok": False, "last_error": "KeyError: article_title"}
        result = triage_source("test-source", info)
        assert result["category"] == "page_structure_change"

    def test_transient_source(self):
        info = {"ok": False, "last_error": "Connection timed out"}
        result = triage_source("test-source", info)
        assert result["category"] == "transient_network"