from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import fetch_cn_journals


def test_management_world_stops_inside_its_internal_budget() -> None:
    opener = Mock()
    opener.open.side_effect = TimeoutError("upstream timed out")
    journal = {
        "id": "journal-379b4022ce",
        "title": "管理世界",
        "short_name": "管理世界",
        "fields": ["chinese"],
    }
    clock = iter(range(0, 200, 10))

    with patch.object(fetch_cn_journals.urllib.request, "build_opener", return_value=opener), patch.object(
        fetch_cn_journals.time, "monotonic", side_effect=lambda: next(clock)
    ):
        records = fetch_cn_journals.fetch_glsj(journal, 20)

    assert records == []
    assert fetch_cn_journals.GLSJ_LAST_NOTE == "time-budget-exhausted"
    assert opener.open.call_count < 10


def test_remaining_timeout_never_runs_past_deadline() -> None:
    with patch.object(fetch_cn_journals.time, "monotonic", return_value=12.0):
        assert fetch_cn_journals.remaining_timeout(20.0, 5) == 5
        assert fetch_cn_journals.remaining_timeout(12.0, 5) is None
