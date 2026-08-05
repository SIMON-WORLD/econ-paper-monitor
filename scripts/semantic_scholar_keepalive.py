"""Daily keep-alive probe for the Semantic Scholar API key.

Semantic Scholar prunes API keys that stay inactive for roughly 60 days
(official breaking-change note, November 2024).  The data workflow runs this
once per update cycle so the key is used regularly, and the result is written
to ``data/semantic_scholar_keepalive.json`` where the health-issue monitor can
alert well before the prune window.

The script never prints credentials.  Without a configured key it records an
honest ``not_configured`` state and exits 0 so the update workflow is not
blocked; the alert is raised by open_health_issues.py instead.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from common import DATA_DIR, USER_AGENT, now_iso, read_json, write_json

KEEPALIVE_DOI = "10.1038/nature14539"  # stable paper indexed by Semantic Scholar
KEEPALIVE_URL = (
    "https://api.semanticscholar.org/graph/v1/paper/"
    f"DOI:{KEEPALIVE_DOI}?fields=paperId"
)
TIMEOUT_SECONDS = 20


def _api_key() -> str:
    return (
        os.environ.get("S2_API_KEY")
        or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        or ""
    ).strip()


def probe(key: str) -> dict[str, object]:
    """Return a keepalive state record after one authenticated request."""
    base = {
        "checked_at": now_iso(),
        "doi": KEEPALIVE_DOI,
        "key_configured": bool(key),
    }
    if not key:
        base.update(
            {
                "ok": False,
                "status_code": None,
                "reason": "not_configured",
                "detail": "SEMANTIC_SCHOLAR_API_KEY / S2_API_KEY is not set in the workflow.",
            }
        )
        return base
    request = urllib.request.Request(
        KEEPALIVE_URL,
        headers={
            "User-Agent": USER_AGENT,
            "x-api-key": key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
            base.update(
                {
                    "ok": True,
                    "status_code": response.status,
                    "reason": "ok",
                    "detail": f"paperId={payload.get('paperId')}",
                }
            )
            return base
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            base.update(
                {
                    "ok": False,
                    "status_code": exc.code,
                    "reason": "invalid_key",
                    "detail": f"HTTP {exc.code}: key rejected by Semantic Scholar.",
                }
            )
        elif exc.code == 429:
            # The key is active and being used; the request was throttled.
            base.update(
                {
                    "ok": True,
                    "status_code": exc.code,
                    "reason": "rate_limited",
                    "detail": "HTTP 429: keep-alive request throttled; key remains active.",
                }
            )
        else:
            base.update(
                {
                    "ok": False,
                    "status_code": exc.code,
                    "reason": "http_error",
                    "detail": f"HTTP {exc.code}: {exc.reason}",
                }
            )
        return base
    except Exception as exc:  # noqa: BLE001
        base.update(
            {
                "ok": False,
                "status_code": None,
                "reason": "network_error",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )
        return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)

    state = probe(_api_key())
    write_json(args.data_dir / "semantic_scholar_keepalive.json", state)
    print(
        f"semantic_scholar_keepalive ok={state['ok']} "
        f"reason={state.get('reason')} status={state.get('status_code')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())