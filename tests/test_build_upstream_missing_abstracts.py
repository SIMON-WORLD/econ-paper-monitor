from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_upstream_missing_abstracts import (  # noqa: E402
    build_list,
    looks_like_book_review,
    missing_abstract,
    upstream_reason,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_with_doi_is_not_in_upstream_list(tmp_path: Path):
    data_dir = tmp_path / "data"
    daily = data_dir / "daily"
    daily.mkdir(parents=True)
    write_json(daily / "2026-08-14.json", [{"doi": "10.1234/x", "title": "A", "url": "u"}])
    write_json(data_dir / "seen.json", {"papers": {}})

    report = build_list(data_dir)

    assert report["without_doi_upstream"] == 0


def test_no_doi_missing_abstract_is_listed(tmp_path: Path):
    data_dir = tmp_path / "data"
    daily = data_dir / "daily"
    daily.mkdir(parents=True)
    write_json(
        daily / "2026-08-14.json",
        [{"title": "B", "url": "u2", "source": "cnki-rss", "source_type": "cn_journal"}],
    )
    write_json(data_dir / "seen.json", {"papers": {}})

    report = build_list(data_dir)

    assert report["without_doi_upstream"] == 1
    assert report["records"][0]["reason"] == "cn_upstream_no_abstract"


def test_book_review_title_as_abstract_is_fixed(tmp_path: Path):
    data_dir = tmp_path / "data"
    daily = data_dir / "daily"
    daily.mkdir(parents=True)
    record = {
        "title": "Some Book. By Author, ISBN: 978-1-234",
        "url": "https://example.test/review",
        "abstract": "Some Book. By Author, ISBN: 978-1-234",
        "journal": "AJARE",
    }
    write_json(daily / "2026-08-14.json", [record])
    write_json(data_dir / "seen.json", {"papers": {}})

    report = build_list(data_dir)

    persisted = json.loads((daily / "2026-08-14.json").read_text(encoding="utf-8"))[0]
    assert persisted["abstract"] is None
    assert persisted["abstract_status_code"] == "book_review_title_as_abstract"
    assert report["daily_abstract_as_title_fixed"] == 1
    assert report["records"][0]["reason"] == "book_review"


def test_long_book_review_title_is_shortened(tmp_path: Path):
    data_dir = tmp_path / "data"
    daily = data_dir / "daily"
    daily.mkdir(parents=True)
    long_title = (
        "Some Book. By Author, ISBN: 978-1-234 " * 30
    )
    record = {"title": long_title, "url": "https://example.test/review"}
    write_json(daily / "2026-08-14.json", [record])
    write_json(data_dir / "seen.json", {"papers": {}})

    build_list(data_dir)

    persisted = json.loads((daily / "2026-08-14.json").read_text(encoding="utf-8"))[0]
    assert len(persisted["title"]) < len(long_title)
    assert "By Author" not in persisted["title"]
    assert persisted["raw_data"]["book_review_full_title"] == long_title.strip()


def test_helpers():
    assert missing_abstract({"abstract": ""}) is True
    assert looks_like_book_review({"title": "A review with ISBN 123"}) is True
    assert upstream_reason({"source": "working_papers", "source_type": "working_paper"}) == "working_paper_no_abstract"


def test_repo_upstream_list_matches_daily_missing_abstracts_without_doi():
    root = ROOT
    upstream = json.loads((root / "data" / "upstream_missing_abstracts.json").read_text(encoding="utf-8"))
    daily_missing_without_doi = 0
    for path in sorted((root / "data" / "daily").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for record in payload:
            if missing_abstract(record) and not record.get("doi"):
                daily_missing_without_doi += 1

    assert upstream["without_doi_upstream"] == daily_missing_without_doi
