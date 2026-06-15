"""Apply manually verified journal ISSN and publisher metadata."""

from __future__ import annotations

from common import DATA_DIR, load_journals, write_journals


UPDATES = {
    "economic-journal": {
        "issn": "1468-0297",
        "publisher": "Oxford University Press",
    },
    "american-economic-review-insights": {
        "issn": "2640-2068",
        "publisher": "American Economic Association",
    },
    "journal-of-economic-behavior-and-organization": {
        "issn": "1879-1751",
        "publisher": "Elsevier",
    },
    "journal-of-economics-and-management-strategy": {
        "issn": "1530-9134",
        "publisher": "Wiley Periodicals, LLC",
    },
    "journal-ba9f46c919": {
        "issn": "0577-9154",
        "publisher": "中国社会科学院",
    },
    "journal-379b4022ce": {
        "issn": "1002-5502",
        "publisher": "国务院发展研究中心",
    },
    "journal-679eaa2a0c": {
        "issn": "1002-9621",
        "publisher": "中国社会科学院、中国世界经济学会与世界经济与政治研究所",
    },
    "journal-edcb877d78": {
        "issn": "1000-3894",
        "publisher": "中国社会科学院数量经济与技术经济研究所",
    },
    "journal-bf2aa9381f": {
        "issn": "1006-480X",
        "publisher": "中国社会科学院、中国社会科学院工业经济研究所",
    },
    "journal-f69300dae2": {
        "issn": "1002-8870",
        "publisher": "中国社会科学院农村发展研究所",
    },
}


def set_crossref_issn(journal: dict, issn: str) -> None:
    sources = journal.setdefault("sources", [])
    for source in sources:
        if source.get("type") == "crossref":
            source["issn"] = issn
            return
    sources.append({"type": "crossref", "issn": issn})


def main() -> None:
    path = DATA_DIR / "journals.yml"
    journals = load_journals(path)
    changed = 0
    for journal in journals:
        update = UPDATES.get(str(journal.get("id")))
        if not update:
            continue
        journal["issn"] = update["issn"]
        journal["publisher"] = update["publisher"]
        set_crossref_issn(journal, update["issn"])
        changed += 1
    write_journals(path, journals)
    print(f"updated {changed} journals")


if __name__ == "__main__":
    main()
