from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "update.yml"


def read_workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_full_schedule_moved_off_beijing_peak() -> None:
    text = read_workflow()
    assert '- cron: "30 11 * * *"' in text
    assert '- cron: "30 6 * * *"' not in text
    assert 'FULL_SCHEDULES: "30 18 * * *|30 0 * * *|30 11 * * *|30 12 * * *"' in text
    assert "Beijing 02:30, 08:30, 19:30, and 20:30" in text


def test_deepseek_model_is_pinned_for_llm_steps() -> None:
    text = read_workflow()
    assert text.count("DEEPSEEK_MODEL: deepseek-chat") >= 2


def test_light_mode_disables_translation() -> None:
    text = read_workflow()
    assert 'TRANSLATE_LIMIT="0"' in text
    assert 'TRANSLATE_LIMIT="160"' in text
    assert "steps.mode.outputs.translate_limit != '0'" in text


def test_ai_china_relevance_runs_only_in_full() -> None:
    text = read_workflow()
    assert "steps.mode.outputs.mode == 'full' && (github.event_name != 'schedule' || contains(env.FULL_SCHEDULES, github.event.schedule) || steps.watchdog.outputs.decision == 'run')" in text
