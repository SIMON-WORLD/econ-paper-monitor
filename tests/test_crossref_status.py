from __future__ import annotations

from pathlib import Path
import json
import sys
from email.message import Message
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_crossref


ROOT = Path(__file__).resolve().parents[1]


def test_crossref_aggregate_status_is_fail_closed() -> None:
    source = (ROOT / "scripts" / "fetch_crossref.py").read_text(encoding="utf-8")
    assert "failures = 0" in source
    assert "failures += 1" in source
    assert "ok=failures == 0" in source


def test_source_health_publishes_actionable_coverage_debt() -> None:
    source = (ROOT / "scripts" / "audit_source_health.py").read_text(encoding="utf-8")
    assert '"coverage_debt"' in source
    assert '"crossref_only"' in source
    assert "next_action" in source


def test_crossref_429_is_retried_and_retry_after_is_honored() -> None:
    headers = Message()
    headers["Retry-After"] = "0"
    rate_limit = urllib.error.HTTPError("https://api.crossref.org", 429, "rate limited", headers, None)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"message": {"items": []}}).encode("utf-8")

    with patch.object(fetch_crossref.urllib.request, "urlopen", side_effect=[rate_limit, Response()]), patch.object(
        fetch_crossref, "polite_sleep"
    ) as sleep_mock:
        result = fetch_crossref.crossref_get(
            "https://api.crossref.org/works", {}, timeout=1, retries=1, sleep=0.1
        )

    assert result == {"message": {"items": []}}
    sleep_mock.assert_called_once()
