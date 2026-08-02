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


def make_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    write_json(data_dir / "seen.json", {"papers": {}})
    return data_dir


class TestManualHelpers:
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
