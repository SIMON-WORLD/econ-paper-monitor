"""Compare local coverage with Alohomora's public paper feed.

This is a local diagnostic sentinel, not an ingestion source.  It helps spot
candidate gaps in our journal monitor by comparing titles/DOIs against an
external public tracker.
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from common import DATA_DIR, ROOT, read_json, write_json


ALO_API = "https://api3.alohomora.live"
OUT_PATH = ROOT / "local_admin" / "alohomora_coverage.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ALIASES = {
    "AE Latest": "Applied Economics",
    "AEJ: Applied Economics Forthcoming": "American Economic Journal: Applied Economics",
    "AEJ: Economic Policy Forthcoming": "American Economic Journal: Economic Policy",
    "AEJ: Macroeconomics Forthcoming": "American Economic Journal: Macroeconomics",
    "AER Forthcoming": "American Economic Review",
    "EL in Press": "Economics Letters",
    "FP in Progress": "Food Policy",
    "GEB in Press": "Games and Economic Behavior",
    "JA&E in Press": "Journal of Accounting and Economics",
    "JAE Early View": "Journal of Applied Econometrics",
    "JBF in Press": "Journal of Banking and Finance",
    "JDE in Press": "Journal of Development Economics",
    "JEDC in Progress": "Journal of Economic Dynamics and Control",
    "JEBO in Press": "Journal of Economic Behavior and Organization",
    "JEEM in Press": "Journal of Environmental Economics and Management",
    "JFE in Progress": "Journal of Financial Economics",
    "JHE in Press": "Journal of Health Economics",
    "J Macro in Progress": "Journal of Macroeconomics",
    "JPubE in Progress": "Journal of Public Economics",
    "JUE in Progress": "Journal of Urban Economics",
    "MS Advance": "Management Science",
    "OBES Early View": "Oxford Bulletin of Economics and Statistics",
    "RED in Progress": "Review of Economic Dynamics",
    "RES Advance": "Review of Economic Studies",
    "REStat Current": "Review of Economics and Statistics",
    "WE Early View": "The World Economy",
    "WD in Progress": "World Development",
}


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "econ-paper-monitor-audit/1.0"})
    with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def norm_title(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").lower())).strip()


def doi_from_url(value: str | None) -> str:
    match = re.search(r"(10\.\d{4,9}/[^\s\"<>]+)", value or "", re.I)
    return match.group(1).lower().rstrip(").,;") if match else ""


def local_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((DATA_DIR / "daily").glob("*.json")):
        payload = read_json(path, [])
        if isinstance(payload, list):
            records.extend(record for record in payload if isinstance(record, dict))
    return records


def local_keys(records: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    titles = {norm_title(str(record.get("title") or "")) for record in records if record.get("title")}
    dois = {str(record.get("doi") or "").lower() for record in records if record.get("doi")}
    for record in records:
        doi = doi_from_url(str(record.get("url") or ""))
        if doi:
            dois.add(doi)
    return titles, dois


def is_china_like(record: dict[str, Any]) -> bool:
    blob = " ".join(str(record.get(key) or "") for key in ("title", "author", "journal"))
    return bool(re.search(r"\b(china|chinese|rmb|renminbi|hong kong|taiwan)\b", blob, re.I))


def monitor_names() -> set[str]:
    text = ""
    for path in (DATA_DIR / "journals.yml", DATA_DIR / "working_paper_sources.yml"):
        if path.exists():
            text += "\n" + path.read_text(encoding="utf-8")
    names = set()
    for match in re.finditer(r"(?m)^\s*(?:-\s*)?(?:name|journal|title):\s*[\"']?([^\"'\n#]+)", text):
        names.add(norm_title(match.group(1).strip()))
    return names


def main() -> None:
    remote_payload = fetch_json(ALO_API)
    papers = [item for item in remote_payload.get("papers", []) if isinstance(item, dict)]
    titles, dois = local_keys(local_records())
    known_names = monitor_names()

    missing: list[dict[str, Any]] = []
    matched = 0
    for paper in papers:
        title = norm_title(str(paper.get("title") or ""))
        doi = doi_from_url(str(paper.get("link") or ""))
        if title in titles or (doi and doi in dois):
            matched += 1
            continue
        journal_label = str(paper.get("journal") or "")
        mapped = ALIASES.get(journal_label, journal_label)
        missing.append(
            {
                "date": paper.get("date"),
                "first_seen_at": paper.get("fdate"),
                "journal": journal_label,
                "mapped_journal": mapped,
                "in_monitor_list": norm_title(mapped) in known_names,
                "china_like": is_china_like(paper),
                "title": paper.get("title"),
                "author": paper.get("author"),
                "link": paper.get("link"),
                "tier": paper.get("tier"),
            }
        )

    summary = {
        "source": ALO_API,
        "alo_count": len(papers),
        "matched_local_daily": matched,
        "possible_missing_count": len(missing),
        "missing_china_like_count": sum(1 for item in missing if item["china_like"]),
        "missing_in_monitor_list_count": sum(1 for item in missing if item["in_monitor_list"]),
        "missing_by_journal": Counter(item["journal"] for item in missing).most_common(50),
        "missing_china_like": [item for item in missing if item["china_like"]][:50],
        "missing_in_monitor_list": [item for item in missing if item["in_monitor_list"]][:80],
        "missing_sample": missing[:50],
    }
    write_json(OUT_PATH, summary)
    print(
        "alohomora coverage: "
        f"alo={summary['alo_count']} matched={summary['matched_local_daily']} "
        f"missing={summary['possible_missing_count']} "
        f"china_like={summary['missing_china_like_count']} "
        f"in_monitor_list={summary['missing_in_monitor_list_count']}"
    )
    print(OUT_PATH)


if __name__ == "__main__":
    main()
