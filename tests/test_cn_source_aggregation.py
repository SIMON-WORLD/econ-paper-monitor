import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from aggregate_cn_status import aggregate_ok
from fetch_cn_journals import all_journal_sources_ok


def test_cn_journal_aggregate_requires_every_child_output():
    rows = [{"ok": True}, {"ok": False}]
    assert aggregate_ok(rows, found_outputs=2) is False
    assert aggregate_ok(rows, found_outputs=1) is False
    assert aggregate_ok([{"ok": True}, {"ok": True}], found_outputs=2) is True


def test_cn_journal_fetch_group_does_not_hide_partial_failure():
    assert all_journal_sources_ok([{"ok": True}, {"ok": False}]) is False
    assert all_journal_sources_ok([{"ok": True}, {"ok": True}]) is True
