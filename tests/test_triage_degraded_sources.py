from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from triage_degraded_sources import classify_failure  # noqa: E402


def test_priority_toc_blocked_group():
    cls = classify_failure(
        {
            "failed_paths": [{"path": "priority-toc", "message": "HTTPError"}],
            "degradation_reason": "failed_path",
            "usable_paths": ["crossref", "openalex-recall"],
            "crossref_status": "ok",
            "rss_status": "none",
        }
    )
    assert cls["group"] == "priority-toc-blocked"
    assert "Crossref fallback" in cls["action"]


def test_cn_endpoint_group():
    cls = classify_failure(
        {
            "failed_paths": [{"path": "cn-journals", "message": "502"}],
            "degradation_reason": "failed_path",
            "usable_paths": ["crossref", "cnki-rss"],
            "crossref_status": "ok",
            "rss_status": "none",
        }
    )
    assert cls["group"] == "cn-endpoint"


def test_single_path_with_healthy_rss_is_marking_artifact():
    cls = classify_failure(
        {
            "failed_paths": [],
            "degradation_reason": "single_path",
            "usable_paths": ["rss", "openalex-recall"],
            "crossref_status": "error",
            "rss_status": "official-generated",
        }
    )
    assert cls["group"] == "marking-single-path"
    assert "单路径降级标记" in cls["summary"]


def test_single_path_crossref_only_is_true_single_path():
    cls = classify_failure(
        {
            "failed_paths": [],
            "degradation_reason": "single_path",
            "usable_paths": ["crossref", "openalex-recall"],
            "crossref_status": "ok",
            "rss_status": "none",
        }
    )
    assert cls["group"] == "true-single-path"