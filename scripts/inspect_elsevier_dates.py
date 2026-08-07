"""Inspect Elsevier Article API date fields for missing-date candidates.

Diagnostic companion to ``recover_metadata_batch.py``.  It reads the metadata
retry queue, calls the Elsevier Article API for a bounded sample of ``10.1016``
DOIs, and writes a sanitized report of the date-related ``coredata`` fields so
the data line can extend parsing from the real API contract.  It never prints
credentials or full API bodies.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

from common import DATA_DIR, now_iso, read_json, write_json
from recover_metadata_batch import _els_rate_limit, _els_request, elsevier_env_credentials


DATE_KEY_TOKENS = ("date", "online", "cover")
DATE_VALUE_KEYS = (
    "prism:coverDisplayDate",
    "prism:coverDate",
    "dc:date",
    "prism:onlineDate",
    "article:onlineDate",
)


def candidate_dois(data_dir: Path, limit: int) -> list[str]:
    payload = read_json(data_dir / "metadata_retry_queue.json", {})
    records = payload.get("records") if isinstance(payload, dict) else []
    dois: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        doi = str(record.get("doi") or "")
        if not doi:
            identity = str(record.get("identity") or "")
            if identity.startswith("doi:"):
                doi = identity[4:]
        doi = doi.strip().casefold()
        if doi.startswith("10.1016/") and doi not in dois:
            dois.append(doi)
        if len(dois) >= limit:
            break
    return dois


def inspect_coredata(core: dict[str, Any], response_headers: dict[str, str]) -> dict[str, Any]:
    date_keys = sorted(key for key in core if any(token in key.casefold() for token in DATE_KEY_TOKENS))
    date_values = {key: str(core.get(key) or "") for key in DATE_VALUE_KEYS if core.get(key) is not None}
    return {
        "date_keys": date_keys,
        "date_values": date_values,
        "_rate_limit": _els_rate_limit(response_headers),
    }


def inspect_doi(doi: str, timeout: int, api_key: str, inst_token: str) -> dict[str, Any]:
    encoded_doi = urllib.parse.quote(doi, safe="")
    url = f"https://api.elsevier.com/content/article/doi/{encoded_doi}?httpAccept=application%2Fjson"
    if not api_key:
        return {"doi": doi, "status": "not_configured"}
    try:
        body, response_headers = _els_request(url, timeout, api_key, inst_token)
        payload = json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        status = "not_found" if exc.code == 404 else "http_error"
        return {"doi": doi, "status": status, "_rate_limit": _els_rate_limit(exc.headers or {})}
    except Exception:
        return {"doi": doi, "status": "http_error"}
    response = payload.get("full-text-retrieval-response") if isinstance(payload, dict) else None
    core = response.get("coredata") if isinstance(response, dict) else None
    if not isinstance(core, dict):
        return {"doi": doi, "status": "not_found", "_rate_limit": _els_rate_limit(response_headers)}
    item = inspect_coredata(core, response_headers)
    item["doi"] = doi
    item["status"] = "available"
    return item


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    output = args.output or (args.data_dir / "elsevier_date_inspection.json")
    api_key, inst_token = elsevier_env_credentials()
    dois = candidate_dois(args.data_dir, args.limit)
    items = [inspect_doi(doi, args.timeout, api_key, inst_token) for doi in dois]
    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    report = {
        "checked_at": now_iso(),
        "credentials_configured": bool(api_key),
        "total": len(items),
        "status_counts": status_counts,
        "items": items,
    }
    write_json(output, report)
    print(f"wrote {output} (total={len(items)} statuses={status_counts})")


if __name__ == "__main__":
    main()
