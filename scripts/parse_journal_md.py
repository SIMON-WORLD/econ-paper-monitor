"""Parse the Markdown journal monitor list into data/journals.yml.

The input file is expected to contain Markdown tables with journal name,
abbreviation, Chinese name, optional field, and private priority columns.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from collections import OrderedDict
from pathlib import Path


FIELD_MAP = {
    "综合顶刊": ("general", "综合"),
    "一流综合期刊": ("general", "综合"),
    "其他综合期刊": ("general", "综合"),
    "博弈顶刊": ("game_theory", "博弈与理论"),
    "其他博弈": ("game_theory", "博弈与理论"),
    "理论顶刊": ("theory", "博弈与理论"),
    "其他理论": ("theory", "博弈与理论"),
    "产业顶刊": ("industrial_organization", "产业、微观、行为与组织"),
    "其他产业": ("industrial_organization", "产业、微观、行为与组织"),
    "微观顶刊": ("microeconomics", "产业、微观、行为与组织"),
    "其他微观": ("microeconomics", "产业、微观、行为与组织"),
    "行为和组织顶刊": ("behavior_organization", "产业、微观、行为与组织"),
    "其他行为和组织": ("behavior_organization", "产业、微观、行为与组织"),
    "公共和政治经济学顶刊": ("public_political", "公共、政治、经济史与国际经济学"),
    "其他公共和政治经济学": ("public_political", "公共、政治、经济史与国际经济学"),
    "经济史顶刊": ("economic_history", "公共、政治、经济史与国际经济学"),
    "其他经济史": ("economic_history", "公共、政治、经济史与国际经济学"),
    "国际经济学顶刊": ("international", "公共、政治、经济史与国际经济学"),
    "其他国际经济学": ("international", "公共、政治、经济史与国际经济学"),
    "金融三大刊": ("finance", "金融、发展、实证应用"),
    "发展顶刊": ("development", "金融、发展、实证应用"),
    "其他发展": ("development", "金融、发展、实证应用"),
    "实证、应用顶刊": ("applied_empirical", "金融、发展、实证应用"),
    "其他实证、应用": ("applied_empirical", "金融、发展、实证应用"),
    "城市经济学顶刊": ("urban", "城市、宏观、人口、劳动、计量、环境、实验"),
    "宏观顶刊": ("macroeconomics", "城市、宏观、人口、劳动、计量、环境、实验"),
    "其他宏观": ("macroeconomics", "城市、宏观、人口、劳动、计量、环境、实验"),
    "人口经济学顶刊": ("population", "城市、宏观、人口、劳动、计量、环境、实验"),
    "劳动顶刊": ("labor", "城市、宏观、人口、劳动、计量、环境、实验"),
    "计量顶刊": ("econometrics", "城市、宏观、人口、劳动、计量、环境、实验"),
    "环境经济学顶刊": ("environmental", "城市、宏观、人口、劳动、计量、环境、实验"),
    "实验经济学顶刊": ("experimental", "城市、宏观、人口、劳动、计量、环境、实验"),
    "法律与比较经济学": ("law_comparative", "法律与比较经济学"),
    "农业、环境、资源与乡村研究": ("agriculture_environment_resource", "农业、环境、资源与乡村研究"),
    "中文顶刊": ("chinese", "中文期刊"),
}


def slugify(value: str) -> str:
    value = value.lower().replace("&", " and ")
    slug = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if slug:
        return slug
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"journal-{digest}"


def split_aliases(value: str) -> list[str]:
    aliases = [part.strip() for part in re.split(r"\s*/\s*", value) if part.strip()]
    return aliases or [value.strip()]


def parse_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def add_unique(items: list[str], values: list[str]) -> None:
    for value in values:
        if value and value not in items:
            items.append(value)


def field_info(raw_field: str, section: str) -> tuple[str, str]:
    key = raw_field or section
    if key in FIELD_MAP:
        return FIELD_MAP[key]
    section_info = FIELD_MAP.get(section)
    if section_info:
        return section_info
    return slugify(key), key


def parse_markdown(path: Path) -> list[dict[str, object]]:
    journals: OrderedDict[str, dict[str, object]] = OrderedDict()
    section = ""
    headers: list[str] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            section = line.removeprefix("## ").strip()
            headers = []
            continue
        if not line.startswith("|"):
            continue
        cells = parse_table_row(line)
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        if any(cell in {"期刊", "领域", "缩写", "常用缩写", "中文名", "优先级"} for cell in cells):
            headers = cells
            continue
        if not headers:
            continue

        row = {headers[index]: cells[index] for index in range(min(len(headers), len(cells)))}
        title = row.get("期刊", "").strip()
        if not title:
            continue

        short_name = row.get("常用缩写") or row.get("缩写") or title
        chinese_name = row.get("中文名") or title
        private_priority = row.get("优先级", "")
        raw_field = row.get("领域", "")
        field_code, public_group = field_info(raw_field, section)
        key = title.casefold()

        if key not in journals:
            journals[key] = {
                "id": slugify(title),
                "title": title,
                "short_name": split_aliases(short_name)[0],
                "aliases": split_aliases(short_name),
                "chinese_name": chinese_name,
                "fields": [],
                "public_group": public_group,
                "priority_private": private_priority,
                "issn": None,
                "publisher": None,
                "sources": [
                    {"type": "rss", "url": None},
                    {"type": "crossref", "issn": None},
                ],
            }

        journal = journals[key]
        add_unique(journal["fields"], [field_code])
        add_unique(journal["aliases"], split_aliases(short_name))
        if private_priority and not journal["priority_private"]:
            journal["priority_private"] = private_priority

    return list(journals.values())


def render_yaml(journals: list[dict[str, object]]) -> str:
    lines = [
        "# Generated by scripts/parse_journal_md.py from journal_monitor_list.md.",
        "# priority_private is for local cadence/ranking only; do not display it on public pages.",
        "journals:",
    ]

    for journal in journals:
        lines.extend(
            [
                f"  - id: {yaml_quote(journal['id'])}",
                f"    title: {yaml_quote(journal['title'])}",
                f"    short_name: {yaml_quote(journal['short_name'])}",
                "    aliases:",
            ]
        )
        for alias in journal["aliases"]:
            lines.append(f"      - {yaml_quote(alias)}")
        lines.extend(
            [
                f"    chinese_name: {yaml_quote(journal['chinese_name'])}",
                "    fields:",
            ]
        )
        for field in journal["fields"]:
            lines.append(f"      - {yaml_quote(field)}")
        lines.extend(
            [
                f"    public_group: {yaml_quote(journal['public_group'])}",
                f"    priority_private: {yaml_quote(journal['priority_private'])}",
                "    issn: null",
                "    publisher: null",
                "    sources:",
                "      - type: rss",
                "        url: null",
                "      - type: crossref",
                "        issn: null",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    journals = parse_markdown(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_yaml(journals), encoding="utf-8")
    print(f"Wrote {len(journals)} journals to {args.output}")


if __name__ == "__main__":
    main()
