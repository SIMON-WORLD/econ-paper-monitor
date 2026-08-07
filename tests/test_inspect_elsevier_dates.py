from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import inspect_elsevier_dates  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_candidate_dois_reads_retry_queue(tmp_path) -> None:
    write_json(
        tmp_path / "metadata_retry_queue.json",
        {
            "records": [
                {"identity": "doi:10.1016/j.foodpol.2026.103163", "title": "A"},
                {"identity": "doi:10.1111/j.1", "title": "B"},
                {"doi": "10.1016/j.jdeveco.2026.103880", "title": "C"},
            ]
        },
    )

    dois = inspect_elsevier_dates.candidate_dois(tmp_path, 10)

    assert dois == [
        "10.1016/j.foodpol.2026.103163",
        "10.1016/j.jdeveco.2026.103880",
    ]


def test_inspect_coredata_collects_only_date_fields() -> None:
    core = {
        "prism:coverDisplayDate": "Available online 6 August 2026",
        "dc:title": "Example paper",
    }

    item = inspect_elsevier_dates.inspect_coredata(core, {"X-RateLimit-Remaining": "100"})

    assert "prism:coverDisplayDate" in item["date_keys"]
    assert "dc:title" not in item["date_keys"]
    assert item["date_values"]["prism:coverDisplayDate"] == "Available online 6 August 2026"
    assert item["_rate_limit"]["X-RateLimit-Remaining"] == "100"


def test_main_writes_sanitized_report(tmp_path) -> None:
    payload = json.dumps(
        {
            "full-text-retrieval-response": {
                "coredata": {
                    "prism:coverDisplayDate": "Available online 6 August 2026",
                    "dc:title": "Example paper",
                }
            }
        }
    )
    write_json(
        tmp_path / "metadata_retry_queue.json",
        {"records": [{"identity": "doi:10.1016/j.foodpol.2026.103163", "title": "A"}]},
    )
    output = tmp_path / "report.json"
    with patch.dict(
        os.environ,
        {"ELSEVIER_API_KEY": "secret-key", "ELSEVIER_INST_TOKEN": "secret-token"},
        clear=False,
    ), patch.object(inspect_elsevier_dates, "_els_request", return_value=(payload, {})), patch.object(
        sys,
        "argv",
        ["inspect", "--data-dir", str(tmp_path), "--limit", "5", "--output", str(output)],
    ):
        inspect_elsevier_dates.main()

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["credentials_configured"] is True
    assert report["status_counts"]["available"] == 1
    item = report["items"][0]
    assert item["status"] == "available"
    assert item["date_values"]["prism:coverDisplayDate"] == "Available online 6 August 2026"
    assert "secret-key" not in output.read_text(encoding="utf-8")


def test_main_reports_not_configured_without_secrets(tmp_path) -> None:
    write_json(
        tmp_path / "metadata_retry_queue.json",
        {"records": [{"identity": "doi:10.1016/j.foodpol.2026.103163", "title": "A"}]},
    )
    output = tmp_path / "report.json"
    with patch.dict(os.environ, {}, clear=True), patch.object(
        sys,
        "argv",
        ["inspect", "--data-dir", str(tmp_path), "--limit", "5", "--output", str(output)],
    ):
        inspect_elsevier_dates.main()

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["credentials_configured"] is False
    assert report["status_counts"]["not_configured"] == 1
