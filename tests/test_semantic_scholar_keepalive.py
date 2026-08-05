"""Tests for the Semantic Scholar API key keep-alive probe."""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from semantic_scholar_keepalive import main, probe  # noqa: E402


def read_keepalive(tmp_path: Path) -> dict:
    path = tmp_path / "semantic_scholar_keepalive.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_no_key_records_not_configured(tmp_path: Path) -> None:
    with patch.dict("os.environ", {}, clear=True):
        code = main(["--data-dir", str(tmp_path)])
    assert code == 0
    state = read_keepalive(tmp_path)
    assert state["ok"] is False
    assert state["reason"] == "not_configured"
    assert state["status_code"] is None
    assert state["key_configured"] is False


def test_successful_probe_marks_ok(tmp_path: Path) -> None:
    class FakeResponse:
        status = 200

        def read(self) -> bytes:
            return b'{"paperId": "abc123"}'

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    with patch.dict("os.environ", {"SEMANTIC_SCHOLAR_API_KEY": "test-key"}, clear=True), patch(
        "urllib.request.urlopen", return_value=FakeResponse()
    ):
        code = main(["--data-dir", str(tmp_path)])
    assert code == 0
    state = read_keepalive(tmp_path)
    assert state["ok"] is True
    assert state["reason"] == "ok"
    assert state["status_code"] == 200
    assert state["detail"] == "paperId=abc123"


def test_invalid_key_records_invalid(tmp_path: Path) -> None:
    exc = urllib.error.HTTPError("https://api.semanticscholar.org/", 401, "Unauthorized", {}, None)
    with patch.dict("os.environ", {"S2_API_KEY": "bad-key"}, clear=True), patch(
        "urllib.request.urlopen", side_effect=exc
    ):
        state = probe("bad-key")
    assert state["ok"] is False
    assert state["reason"] == "invalid_key"
    assert state["status_code"] == 401


def test_rate_limited_counts_as_active(tmp_path: Path) -> None:
    exc = urllib.error.HTTPError("https://api.semanticscholar.org/", 429, "Too Many Requests", {}, None)
    with patch("urllib.request.urlopen", side_effect=exc):
        state = probe("test-key")
    assert state["ok"] is True
    assert state["reason"] == "rate_limited"
    assert state["status_code"] == 429


def test_server_error_records_http_error(tmp_path: Path) -> None:
    exc = urllib.error.HTTPError("https://api.semanticscholar.org/", 500, "Internal", {}, None)
    with patch("urllib.request.urlopen", side_effect=exc):
        state = probe("test-key")
    assert state["ok"] is False
    assert state["reason"] == "http_error"
    assert state["status_code"] == 500