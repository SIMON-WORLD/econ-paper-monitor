"""Repair workflow status fields from recorded history."""

from __future__ import annotations

from status import load_status, save_status


def main() -> None:
    status = load_status()
    workflow = status.setdefault("workflow", {})
    history = workflow.get("history") or []
    last_by_mode: dict[str, str] = {}
    for entry in history:
        mode = str(entry.get("mode") or "")
        finished_at = str(entry.get("finished_at") or "")
        if mode and finished_at and mode not in last_by_mode:
            last_by_mode[mode] = finished_at
    for mode, key in (
        ("full", "last_full_finished_at"),
        ("light", "last_light_finished_at"),
        ("single", "last_single_finished_at"),
    ):
        if last_by_mode.get(mode):
            workflow[key] = last_by_mode[mode]
    save_status(status)
    print(
        "workflow status repaired:",
        "full=", workflow.get("last_full_finished_at"),
        "light=", workflow.get("last_light_finished_at"),
    )


if __name__ == "__main__":
    main()
