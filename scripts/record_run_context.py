"""Record user-facing workflow run context.

This runs near the end of GitHub Actions, after scraping/enrichment work has
finished and before rendering the site. It gives dashboards a reliable
"last monitored" timestamp instead of relying on intermediate pipeline steps.
"""

from __future__ import annotations

import argparse

from common import today_str
from status import now, record_source, record_workflow_run


MODE_LABELS = {
    "light": "\u5feb\u901f\u76d1\u6d4b",
    "full": "\u5168\u91cf\u76d1\u6d4b",
    "single": "\u5355\u671f\u520a\u76d1\u6d4b",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="light")
    parser.add_argument("--event", default="")
    parser.add_argument("--schedule", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-url", default="")
    args = parser.parse_args()

    finished_at = now()
    mode = args.mode or "light"
    label = MODE_LABELS.get(mode, mode)
    summary = {
        "mode": mode,
        "mode_label": label,
        "event": args.event,
        "schedule": args.schedule,
        "run_id": args.run_id,
        "run_url": args.run_url,
        "date": today_str(),
        "finished_at": finished_at,
        "updated_at": finished_at,
    }
    record_workflow_run(summary)
    record_source("workflow", ok=True, count=1, message=f"{label} finished")
    print(f"workflow context recorded: {label} at {finished_at}")


if __name__ == "__main__":
    main()
