from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import artifact_paths as common  # noqa: E402


class RepoRelativePathTests(unittest.TestCase):
    """``data/**`` is committed to a public repository.

    An absolute path in a committed artifact leaks the operator's machine
    layout (``E:\\BaiduSyncdisk\\...``) or the CI runner layout
    (``/home/runner/work/...``). Both have happened, so both are pinned here.
    """

    def test_path_inside_repository_becomes_relative(self) -> None:
        self.assertEqual(
            common.repo_relative_path(ROOT / "data" / "raw" / "rss" / "2026-06-23.json"),
            "data/raw/rss/2026-06-23.json",
        )

    def test_windows_operator_path_is_reduced_to_a_file_name(self) -> None:
        leaked = r"E:\BaiduSyncdisk\Work\Agent_automation\econ-paper-monitor\data\raw\rss\2026-06-23.json"
        value = common.repo_relative_path(leaked)
        self.assertEqual(value, "2026-06-23.json")
        self.assertNotIn("BaiduSyncdisk", value)

    def test_ci_runner_path_is_reduced_to_a_file_name(self) -> None:
        leaked = "/home/runner/work/econ-paper-monitor/econ-paper-monitor/data/raw/rss/a.json"
        self.assertEqual(common.repo_relative_path(leaked), "a.json")

    def test_already_relative_path_is_preserved(self) -> None:
        self.assertEqual(common.repo_relative_path("data/raw/rss/b.json"), "data/raw/rss/b.json")

    def test_persisted_records_are_sanitised_on_merge(self) -> None:
        records = [
            {"_raw_file": r"E:\BaiduSyncdisk\Work\data\raw\rss\2026-06-23.json"},
            {"raw_file": "/home/runner/work/econ-paper-monitor/econ-paper-monitor/data/raw/x.json"},
            {"title": "no path field"},
        ]
        changed = common.sanitize_record_paths(records)
        self.assertEqual(changed, 2)
        self.assertEqual(records[0]["_raw_file"], "2026-06-23.json")
        self.assertEqual(records[1]["raw_file"], "x.json")
        self.assertEqual(records[2], {"title": "no path field"})


if __name__ == "__main__":
    unittest.main()
