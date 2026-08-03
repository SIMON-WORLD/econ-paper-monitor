from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_manual_supplement import (  # noqa: E402
    build_manual_record,
    import_package,
    issue_date_from_label,
    normalize_publisher_abstract,
    parse_manual_authors,
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def package() -> dict:
    return {
        "journal": "管理世界",
        "journal_id": "GLJJ",
        "issn": "1002-5502",
        "issue": "2026年07期",
        "source": "manual-cnki",
        "records": [
            {
                "title": "数据财政的前景研究：企业需求视角",
                "authors": "杨健鹏1梅思雨2 张晗雨3梁若冰3",
                "abstract": "这是一段用于测试的完整中文摘要，讨论数据财政与企业公共数据需求的关系，并给出实证结论与政策含义。",
                "doi": None,
                "url": "https://example.test/cnki/1",
            },
            {
                "title": "数据赋能的两面性：低碳与居民收入增长何以兼得？",
                "authors": "王永进1,2,3周成英1谢芳4",
                "abstract": "这是一段用于测试的完整中文摘要，讨论数字化与绿色化协同发展对碳排放与福利的影响。",
                "doi": None,
                "url": "https://example.test/cnki/2",
            },
        ],
    }


def publisher_package() -> dict:
    return {
        "journal": None,
        "source": "manual-publisher",
        "method": "in-app-browser + ZJU institutional session",
        "extracted_at": "2026-08-02T19:30:00Z",
        "batch": "2026-08-02-sd-abstract-batch-1",
        "records": [
            {
                "journal": "Economics Letters",
                "doi": "10.1016/j.econlet.2026.113122",
                "title": "Peer-confirming equilibrium in anchor games",
                "authors": ["Shinya Sugiura"],
                "abstract": "Abstract\nPeer-confirming equilibrium is the paper's core result.",
                "url": "https://www.sciencedirect.com/science/article/pii/S0165176526003186",
            },
            {
                "journal": "Games and Economic Behavior",
                "doi": "10.1016/j.geb.2026.07.005",
                "title": "Information paths and learning in games",
                "authors": ["Peiran Jiao a", "Heinrich H. Nax b"],
                "abstract": (
                    "Highlights\n• A highlight.\nAbstract\n"
                    "Information paths shape learning outcomes."
                ),
                "url": "https://www.sciencedirect.com/science/article/pii/S0899825626001156",
            },
        ],
    }


def make_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    write_json(data_dir / "seen.json", {"papers": {}})
    return data_dir


class TestManualHelpers:
    def test_normalize_publisher_abstract(self):
        assert (
            normalize_publisher_abstract(
                "Highlights\n• A highlight.\nAbstract\nReal abstract text."
            )
            == "Real abstract text."
        )
        assert normalize_publisher_abstract("Abstract\nPeer result text.") == "Peer result text."
        assert normalize_publisher_abstract(None) == ""

    def test_parse_manual_authors_affiliation_letters(self):
        assert parse_manual_authors(["Shinya Sugiura", "Meng Liu a", "Elie Bouri a j"]) == [
            "Shinya Sugiura",
            "Meng Liu",
            "Elie Bouri",
        ]

    def test_issue_date_from_label(self):
        assert issue_date_from_label("2026年07期") == "2026-07-01"
        assert issue_date_from_label("") == ""

    def test_parse_manual_authors(self):
        assert parse_manual_authors("杨健鹏1梅思雨2 张晗雨3梁若冰3") == [
            "杨健鹏",
            "梅思雨",
            "张晗雨",
            "梁若冰",
        ]
        assert parse_manual_authors("王永进1,2,3周成英1谢芳4") == ["王永进", "周成英", "谢芳"]
        assert parse_manual_authors(None) == []

    def test_build_manual_record_keeps_missing_doi_honest(self):
        record = build_manual_record(
            package()["records"][0],
            package(),
            "cnki_gljj_2026-07_manual_supplement",
            {"id": "journal-379b4022ce", "title": "管理世界", "short_name": "管理世界"},
            0,
        )
        assert "doi" not in record
        assert record["issue_date"] == "2026-07-01"
        assert record["date_confidence"] == "D"
        assert record["source"] == "manual-cnki"
        assert record["authors"] == ["杨健鹏", "梅思雨", "张晗雨", "梁若冰"]


class TestManualImport:
    def test_adds_new_records_and_counts_missing_doi(self, tmp_path: Path):
        data_dir = make_data_dir(tmp_path)
        source = tmp_path / "cnki_gljj_2026-07_manual_supplement.json"
        write_json(source, package())

        report = import_package(source, data_dir=data_dir)

        assert report["added"] == 2
        assert report["matched_backfilled"] == 0
        assert report["missing_doi_count"] == 2
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        assert len(seen["papers"]) == 2
        assert all("doi" not in record for record in seen["papers"].values())

    def test_rerun_is_idempotent(self, tmp_path: Path):
        data_dir = make_data_dir(tmp_path)
        source = tmp_path / "cnki_gljj_2026-07_manual_supplement.json"
        write_json(source, package())

        first = import_package(source, data_dir=data_dir)
        second = import_package(source, data_dir=data_dir)

        assert first["added"] == 2
        assert second["skipped"] == 2
        assert second["added"] == 0
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        assert len(seen["papers"]) == 2

    def test_backfills_existing_record_without_abstract(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        write_json(
            data_dir / "seen.json",
            {
                "papers": {
                    "existing-1": {
                        "id": "existing-1",
                        "title": "数据财政的前景研究：企业需求视角",
                        "journal": "管理世界",
                        "journal_id": "journal-379b4022ce",
                        "abstract": None,
                    }
                }
            },
        )
        source = tmp_path / "cnki_gljj_2026-07_manual_supplement.json"
        write_json(source, package())

        report = import_package(source, data_dir=data_dir)

        assert report["matched_backfilled"] == 1
        assert report["added"] == 1
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        assert seen["papers"]["existing-1"]["abstract"]
        assert seen["papers"]["existing-1"]["abstract_source"] == "manual-cnki"

    def test_upgrades_preview_abstract_to_full_manual_abstract(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        write_json(
            data_dir / "seen.json",
            {
                "papers": {
                    "existing-1": {
                        "id": "existing-1",
                        "title": "数据财政的前景研究：企业需求视角",
                        "journal": "管理世界",
                        "journal_id": "journal-379b4022ce",
                        "abstract": "这是来自 RSS 的预览摘要……",
                        "abstract_completeness": "preview",
                        "abstract_truncated": True,
                    }
                }
            },
        )
        source = tmp_path / "cnki_gljj_2026-07_manual_supplement.json"
        write_json(source, package())

        report = import_package(source, data_dir=data_dir)

        assert report["matched_backfilled"] == 1
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        record = seen["papers"]["existing-1"]
        assert record["abstract"] == package()["records"][0]["abstract"]
        assert record["abstract_completeness"] == "full"
        assert "abstract_truncated" not in record
        assert record["abstract_source"] == "manual-cnki"

    def test_rejects_non_manual_source(self, tmp_path: Path):
        data_dir = make_data_dir(tmp_path)
        source = tmp_path / "bad.json"
        bad = package()
        bad["source"] = "cnki"
        write_json(source, bad)

        try:
            import_package(source, data_dir=data_dir)
        except ValueError as exc:
            assert "manual-" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_doi_is_merged_into_existing_manual_record_idempotently(self, tmp_path: Path):
        data_dir = make_data_dir(tmp_path)
        write_json(
            data_dir / "seen.json",
            {
                "papers": {
                    "manual:cnki_gljj_2026-07_manual_supplement:0": {
                        "id": "manual:cnki_gljj_2026-07_manual_supplement:0",
                        "title": "数据财政的前景研究：企业需求视角",
                        "source": "manual-cnki",
                        "journal": "管理世界",
                        "journal_id": "journal-379b4022ce",
                        "abstract": "已有完整摘要",
                        "abstract_completeness": "full",
                    }
                }
            },
        )
        source = tmp_path / "cnki_gljj_2026-07_manual_supplement.json"
        pkg = package()
        pkg["records"][0]["doi"] = "10.1000/gljj.2026.07001"
        write_json(source, pkg)

        report = import_package(source, data_dir=data_dir)

        assert report["doi_merged"] == 1
        assert report["added"] == 1
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        record = seen["papers"]["manual:cnki_gljj_2026-07_manual_supplement:0"]
        assert record["doi"] == "10.1000/gljj.2026.07001"
        assert "doi:10.1000/gljj.2026.07001" in record["identity_aliases"]

        # Second run must not re-merge or duplicate.
        second = import_package(source, data_dir=data_dir)
        assert second["doi_merged"] == 0
        assert second["skipped"] == 2
        assert second["added"] == 0
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        assert len(seen["papers"]) == 2

    def test_multi_journal_package_uses_record_journal(self, tmp_path: Path):
        data_dir = make_data_dir(tmp_path)
        source = tmp_path / "2026-08-02-sd-abstract-batch-1.json"
        write_json(source, publisher_package())

        report = import_package(source, data_dir=data_dir)

        assert report["added"] == 2
        assert "Economics Letters" in report["journals_used"]
        assert "Games and Economic Behavior" in report["journals_used"]
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        by_doi = {
            str(record.get("doi") or "").casefold(): record
            for record in seen["papers"].values()
            if record.get("doi")
        }
        assert by_doi["10.1016/j.econlet.2026.113122"]["journal_id"] == "economics-letters"
        assert by_doi["10.1016/j.geb.2026.07.005"]["journal_id"] == "games-and-economic-behavior"
        assert by_doi["10.1016/j.geb.2026.07.005"]["abstract"] == (
            "Information paths shape learning outcomes."
        )

    def test_unresolved_record_journal_is_reported_not_dropped(self, tmp_path: Path):
        data_dir = make_data_dir(tmp_path)
        source = tmp_path / "bad-journal.json"
        pkg = {
            "journal": None,
            "source": "manual-publisher",
            "records": [
                {
                    "journal": "Not A Real Journal",
                    "title": "Untitled paper",
                    "doi": "10.1016/j.abc.2026.000001",
                    "abstract": "Real abstract.",
                }
            ],
        }
        write_json(source, pkg)

        report = import_package(source, data_dir=data_dir)

        assert report["skipped"] == 1
        assert report["unresolved_journal_count"] == 1
        assert report["added"] == 0
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        assert len(seen["papers"]) == 0

    def test_doi_exact_match_backfills_seen_and_daily_idempotently(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        write_json(
            data_dir / "seen.json",
            {
                "papers": {
                    "existing-1": {
                        "id": "existing-1",
                        "title": "Peer-confirming equilibrium in anchor games",
                        "doi": "10.1016/j.econlet.2026.113122",
                        "journal": "Economics Letters",
                        "journal_id": "economics-letters",
                        "abstract": None,
                        "abstract_completeness": "missing",
                    }
                }
            },
        )
        daily_dir = data_dir / "daily"
        daily_dir.mkdir(parents=True)
        write_json(
            daily_dir / "2026-07-11.json",
            [
                {
                    "id": "daily-1",
                    "title": "Peer-confirming equilibrium in anchor games",
                    "doi": "10.1016/j.econlet.2026.113122",
                    "journal": "Economics Letters",
                    "abstract": None,
                    "abstract_completeness": "missing",
                }
            ],
        )
        source = tmp_path / "2026-08-02-sd-abstract-batch-1.json"
        write_json(source, publisher_package())

        report = import_package(source, data_dir=data_dir)

        assert report["matched_by_doi"] == 1
        assert report["matched_backfilled"] == 1
        assert report["daily_backfilled"] == 1
        assert report["daily_files_changed"] == 1
        assert report["added"] == 1
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        assert seen["papers"]["existing-1"]["abstract"] == "Peer-confirming equilibrium is the paper's core result."
        assert seen["papers"]["existing-1"]["abstract_source"] == "manual-publisher"
        daily = json.loads((daily_dir / "2026-07-11.json").read_text(encoding="utf-8"))
        assert daily[0]["abstract"] == "Peer-confirming equilibrium is the paper's core result."

        second = import_package(source, data_dir=data_dir)
        assert second["added"] == 0
        assert second["matched_backfilled"] == 0
        assert second["daily_backfilled"] == 0
        assert second["skipped"] == 2

    def test_doi_merges_into_url_only_seen_record(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        write_json(
            data_dir / "seen.json",
            {
                "papers": {
                    "url:abc123": {
                        "id": "url:abc123",
                        "title": "Peer-confirming equilibrium in anchor games",
                        "url": "https://www.sciencedirect.com/science/article/pii/S0165176526003186",
                        "journal": "Economics Letters",
                        "abstract": None,
                    }
                }
            },
        )
        source = tmp_path / "single.json"
        pkg = publisher_package()
        pkg["records"] = [pkg["records"][0]]
        write_json(source, pkg)

        report = import_package(source, data_dir=data_dir)

        assert report["matched_by_title"] == 1
        assert report["doi_merged"] == 1
        assert report["added"] == 0
        seen = json.loads((data_dir / "seen.json").read_text(encoding="utf-8"))
        record = seen["papers"]["url:abc123"]
        assert record["doi"] == "10.1016/j.econlet.2026.113122"
        assert "doi:10.1016/j.econlet.2026.113122" in record["identity_aliases"]
