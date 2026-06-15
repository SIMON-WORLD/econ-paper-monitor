"""Export journals with missing ISSN or publisher for manual review."""

from __future__ import annotations

from common import DATA_DIR, load_journals


def clean(value: object) -> str:
    return str(value or "").replace("|", "\\|")


def main() -> None:
    journals = load_journals(DATA_DIR / "journals.yml")
    missing = [journal for journal in journals if not journal.get("issn") or not journal.get("publisher")]
    lines = [
        "# ISSN 和出版社待补充清单",
        "",
        "请在 `issn` 和 `publisher` 两列补充信息；不确定的留空即可。",
        "",
        "| id | title | chinese_name | short_name | issn | publisher |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for journal in missing:
        lines.append(
            "| "
            + " | ".join(
                [
                    clean(journal.get("id")),
                    clean(journal.get("title")),
                    clean(journal.get("chinese_name")),
                    clean(journal.get("short_name")),
                    clean(journal.get("issn")),
                    clean(journal.get("publisher")),
                ]
            )
            + " |"
        )
    output = DATA_DIR / "journal_metadata_todo.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(missing)} journals to {output}")


if __name__ == "__main__":
    main()
