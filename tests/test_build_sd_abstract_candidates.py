from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_sd_abstract_candidates import (  # noqa: E402
    build_candidates,
    is_missing_abstract,
    is_sd_doi,
    pii_from_record,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def record(record_id: str, **overrides) -> dict:
    base = {
        "id": record_id,
        "title": "A missing-abstract Elsevier paper",
        "journal": "Journal of Development Economics",
        "journal_id": "journal-of-development-economics",
        "detail_key": f"detail-{record_id}",
        "doi": "10.1016/j.jdeveco.2026.100001",
        "url": "https://www.sciencedirect.com/science/article/pii/S0304387826000001",
        "abstract": None,
        "available_online": "2026-07-01",
        "first_seen": "2026-07-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def make_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    write_json(
        data_dir / "seen.json",
        {
            "papers": {
                "sd-recent": record(
                    "sd-recent",
                    title="Recent Elsevier missing abstract",
                    doi="10.1016/j.jdeveco.2026.100001",
                    url="https://www.sciencedirect.com/science/article/pii/S0304387826000001",
                ),
                "wiley-old": record(
                    "wiley-old",
                    title="Old Wiley missing abstract",
                    doi="10.1111/jmcb.13095",
                    url="https://onlinelibrary.wiley.com/doi/10.1111/jmcb.13095",
                    available_online="2025-05-01",
                    first_seen="2025-05-01T00:00:00+00:00",
                ),
                "other-prefix": record(
                    "other-prefix",
                    title="Springer missing abstract",
                    doi="10.1007/s00148-026-01169-9",
                ),
                "sd-with-abstract": record(
                    "sd-with-abstract",
                    title="Elsevier with abstract",
                    abstract="This paper already has an abstract that is long enough to skip.",
                ),
            }
        },
    )
    return data_dir


def test_filters_and_grouping(tmp_path: Path) -> None:
    data_dir = make_data_dir(tmp_path)
    report = build_candidates(data_dir, limit=10)
    assert report["total_candidates"] == 2
    assert set(report["journals"].keys()) == {"Journal of Development Economics"}
    items = report["journals"]["Journal of Development Economics"]
    dois = {item["doi"] for item in items}
    assert dois == {"10.1016/j.jdeveco.2026.100001", "10.1111/jmcb.13095"}
    by_doi = {item["doi"]: item for item in items}
    assert by_doi["10.1016/j.jdeveco.2026.100001"]["pii"] == "S0304387826000001"
    assert "sciencedirect.com" in by_doi["10.1016/j.jdeveco.2026.100001"]["link"]
    assert by_doi["10.1111/jmcb.13095"]["link"] == "https://doi.org/10.1111/jmcb.13095"
    assert all({"doi", "title", "journal", "detail_key"} <= set(item) for item in items)


def test_limit_is_respected(tmp_path: Path) -> None:
    data_dir = make_data_dir(tmp_path)
    report = build_candidates(data_dir, limit=1)
    assert report["total_candidates"] == 1
    items = report["journals"]["Journal of Development Economics"]
    assert items[0]["doi"] == "10.1016/j.jdeveco.2026.100001"


def test_helpers() -> None:
    assert is_missing_abstract({"abstract": ""}) is True
    assert is_missing_abstract({"abstract": "A real abstract"}) is False
    assert is_sd_doi("10.1016/j.jdeveco.2026.100001") is True
    assert is_sd_doi("10.1017/S0003055426000001") is True
    assert is_sd_doi("10.1111/jmcb.13095") is True
    assert is_sd_doi("10.1007/s00148-026-01169-9") is False
    assert pii_from_record({"url": "https://www.sciencedirect.com/science/article/pii/S0304387826000001"}) == "S0304387826000001"
