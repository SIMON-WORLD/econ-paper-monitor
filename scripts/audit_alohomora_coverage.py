"""Compare local coverage with Alohomora's public paper feed.

This is a local diagnostic sentinel, not an ingestion source.  It helps spot
candidate gaps in our journal monitor by comparing titles/DOIs against an
external public tracker.
"""

from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from common import DATA_DIR, ROOT, read_json, write_json


ALO_API = "https://api3.alohomora.live"
OUT_PATH = ROOT / "local_admin" / "alohomora_coverage.json"
MD_OUT_PATH = ROOT / "local_admin" / "alohomora_coverage.md"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ALIASES = {
    "AE Latest": "Applied Economics",
    "AEJ: Applied Economics Forthcoming": "American Economic Journal: Applied Economics",
    "AEJ: Economic Policy Forthcoming": "American Economic Journal: Economic Policy",
    "AEJ: Macroeconomics Forthcoming": "American Economic Journal: Macroeconomics",
    "AER Forthcoming": "American Economic Review",
    "EL in Press": "Economics Letters",
    "EM in Press": "Economic Modelling",
    "EE in Press": "Energy Economics",
    "EEduR in Progress": "Economics of Education Review",
    "EI Early View": "Economic Inquiry",
    "EP in Progress": "Energy Policy",
    "FP in Progress": "Food Policy",
    "GEB in Press": "Games and Economic Behavior",
    "JBR in Progress": "Journal of Business Research",
    "JBES Latest": "Journal of Business and Economic Statistics",
    "JA&E in Press": "Journal of Accounting and Economics",
    "JAE Early View": "Journal of Applied Econometrics",
    "JBF in Press": "Journal of Banking and Finance",
    "JDE in Press": "Journal of Development Economics",
    "JEDC in Progress": "Journal of Economic Dynamics and Control",
    "JEBO in Press": "Journal of Economic Behavior and Organization",
    "JEEM in Press": "Journal of Environmental Economics and Management",
    "JFE in Progress": "Journal of Financial Economics",
    "JHE in Press": "Journal of Health Economics",
    "JASA Latest": "Journal of the American Statistical Association",
    "JCR Advance": "Journal of Consumer Research",
    "JDS Latest": "Journal of Data Science",
    "JEPsy in Progress": "Journal of Economic Psychology",
    "JES Early View": "Journal of Economic Surveys",
    "JFQA Accepted": "Journal of Financial and Quantitative Analysis",
    "JM Online First": "Journal of Marketing",
    "JOEG Advance": "Journal of Economic Geography",
    "JRU Online First": "Journal of Risk and Uncertainty",
    "J Macro in Progress": "Journal of Macroeconomics",
    "JPubE in Progress": "Journal of Public Economics",
    "JUE in Progress": "Journal of Urban Economics",
    "MS Advance": "Management Science",
    "OBES Early View": "Oxford Bulletin of Economics and Statistics",
    "RED in Progress": "Review of Economic Dynamics",
    "RES Advance": "Review of Economic Studies",
    "REStat Current": "Review of Economics and Statistics",
    "RIE Early View": "Review of International Economics",
    "RS Latest": "Regional Studies",
    "TAR Current": "The Accounting Review",
    "WE Early View": "The World Economy",
    "WD in Progress": "World Development",
}

ECON_SCOPE_EXTRA = {
    "Economics of Education Review",
    "Economic Inquiry",
    "Economic Policy",
    "Economics of Education Review",
    "Economic Modelling",
    "Energy Economics",
    "Energy Policy",
    "Oxford Bulletin of Economics and Statistics",
    "Review of International Economics",
    "The World Economy",
}

OUT_OF_SCOPE_HINTS = {
    "Biometrika",
    "Ecological Economics",
    "Journal of Business Research",
    "Journal of Consumer Research",
    "Journal of Data Science",
    "Journal of Marketing",
    "Review of Accounting Studies",
    "The Accounting Review",
}

BROADER_BUT_RELEVANT_HINTS = {
    "Journal of Accounting and Economics",
    "Journal of Business and Economic Statistics",
    "Journal of Business Research",
    "Journal of Economic Geography",
    "Journal of Economic Psychology",
    "Journal of Economic Surveys",
    "Journal of Financial and Quantitative Analysis",
    "Journal of the American Statistical Association",
    "Regional Studies",
}


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "econ-paper-monitor-audit/1.0"})
    with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def norm_title(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").lower())).strip()


def doi_from_url(value: str | None) -> str:
    match = re.search(r"(10\.\d{4,9}/[^\s\"<>]+)", value or "", re.I)
    return match.group(1).lower().rstrip(").,;") if match else ""


def local_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted((DATA_DIR / "daily").glob("*.json")):
        payload = read_json(path, [])
        if isinstance(payload, list):
            records.extend(record for record in payload if isinstance(record, dict))
    return records


def local_keys(records: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    titles = {norm_title(str(record.get("title") or "")) for record in records if record.get("title")}
    dois = {str(record.get("doi") or "").lower() for record in records if record.get("doi")}
    for record in records:
        doi = doi_from_url(str(record.get("url") or ""))
        if doi:
            dois.add(doi)
    return titles, dois


def is_china_like(record: dict[str, Any]) -> bool:
    blob = " ".join(str(record.get(key) or "") for key in ("title", "author", "journal"))
    return bool(re.search(r"\b(china|chinese|rmb|renminbi|hong kong|taiwan)\b", blob, re.I))


def likely_gap_reason(journal_label: str, mapped_journal: str, link: str | None) -> str:
    label = journal_label.lower()
    mapped = mapped_journal.lower()
    url = str(link or "").lower()
    if "early view" in label and ("wiley" in url or "10.1111/" in url):
        return "缺少 Wiley Early View 快速源或未把该期刊加入快速源。"
    if "forthcoming" in label and "aeaweb.org" in url:
        return "AEA forthcoming 页面更新快于 Crossref/RSS，需要把 forthcoming 作为快速源。"
    if "in press" in label or "in progress" in label:
        return "出版社 in press/in progress 页面比 Crossref 更早，需强化 Publisher TOC/PII/RSS 链路。"
    if "latest" in label and "tandfonline.com" in url:
        return "T&F latest 页面可能早于 Crossref，需要补 latest/current issue 抽检。"
    if mapped in {item.lower() for item in ECON_SCOPE_EXTRA}:
        return "属于经济学扩展清单，应决定是否纳入正式监测或外部哨兵。"
    return "需人工复核：可能是清单外来源，也可能是期刊别名未映射。"


def scope_bucket(mapped_journal: str, in_monitor_list: bool) -> str:
    if in_monitor_list:
        return "our_scope"
    if mapped_journal in ECON_SCOPE_EXTRA:
        return "econ_expand_candidate"
    if mapped_journal in BROADER_BUT_RELEVANT_HINTS:
        return "broader_relevant_candidate"
    if mapped_journal in OUT_OF_SCOPE_HINTS:
        return "broader_out_of_scope"
    return "unknown_scope"


def monitor_names() -> set[str]:
    text = ""
    for path in (DATA_DIR / "journals.yml", DATA_DIR / "working_paper_sources.yml"):
        if path.exists():
            text += "\n" + path.read_text(encoding="utf-8")
    names = set()
    for match in re.finditer(r"(?m)^\s*(?:-\s*)?(?:name|journal|title):\s*[\"']?([^\"'\n#]+)", text):
        names.add(norm_title(match.group(1).strip()))
    return names


def md_link(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Untitled").replace("|", "\\|")
    link = str(item.get("link") or "")
    return f"[{title}]({link})" if link else title


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Alohomora 覆盖对比清单",
        "",
        "这份清单用于外部哨兵审计，不把 Alohomora 当作正式入库源。",
        "",
        "## 总览",
        "",
        f"- Alohomora 当前返回：{summary['alo_count']} 篇",
        f"- 本地已匹配：{summary['matched_local_daily']} 篇",
        f"- 未匹配候选：{summary['possible_missing_count']} 篇",
        f"- 我们当前清单内疑似漏抓：{summary['missing_in_monitor_list_count']} 篇",
        f"- 经济学扩展候选：{summary['missing_econ_expand_count']} 篇",
        f"- 更广但可能相关候选：{summary['missing_broader_relevant_count']} 篇",
        f"- 标题疑似中国相关：{summary['missing_china_like_count']} 篇",
        "",
        "## 我们清单内疑似漏抓",
        "",
        "| 日期 | 来源标签 | 映射期刊 | 论文 | 可能原因 |",
        "|---|---|---|---|---|",
    ]
    for item in summary["missing_in_monitor_list"][:80]:
        lines.append(
            f"| {item.get('date') or ''} | {item.get('journal') or ''} | "
            f"{item.get('mapped_journal') or ''} | {md_link(item)} | {item.get('reason') or ''} |"
        )
    if not summary["missing_in_monitor_list"]:
        lines.append("|  |  |  | 暂无 |  |")

    lines += [
        "",
        "## 经济学扩展候选",
        "",
        "这些不一定属于当前正式清单，但和经济学/应用经济学相近，可评估是否纳入。",
        "",
        "| 日期 | 来源标签 | 映射期刊 | 论文 | 建议 |",
        "|---|---|---|---|---|",
    ]
    for item in summary["missing_econ_expand"][:80]:
        lines.append(
            f"| {item.get('date') or ''} | {item.get('journal') or ''} | "
            f"{item.get('mapped_journal') or ''} | {md_link(item)} | {item.get('reason') or ''} |"
        )
    if not summary["missing_econ_expand"]:
        lines.append("|  |  |  | 暂无 |  |")

    lines += [
        "",
        "## 更广但可能相关候选",
        "",
        "这些来源不属于当前核心经济学期刊监测，但和商科、金融、会计、统计或应用研究相关。建议只做外部哨兵，不直接进入首页核心流。",
        "",
        "| 日期 | 来源标签 | 映射期刊 | 论文 | 建议 |",
        "|---|---|---|---|---|",
    ]
    for item in summary["missing_broader_relevant"][:80]:
        lines.append(
            f"| {item.get('date') or ''} | {item.get('journal') or ''} | "
            f"{item.get('mapped_journal') or ''} | {md_link(item)} | {item.get('reason') or ''} |"
        )
    if not summary["missing_broader_relevant"]:
        lines.append("|  |  |  | 暂无 |  |")

    lines += [
        "",
        "## 暂不建议纳入的更广覆盖",
        "",
        "Alohomora 覆盖更广，包含商科、会计、营销、生态、统计等。它们可作为灵感，但不应直接扩大我们的核心监测范围。",
        "",
        "| 来源标签 | 数量 | 说明 |",
        "|---|---:|---|",
    ]
    for journal, count in summary["broader_out_of_scope_by_journal"]:
        lines.append(f"| {journal} | {count} | 当前不属于已确认经济学核心清单 |")

    lines += [
        "",
        "## 标题疑似中国相关但未匹配",
        "",
        "| 日期 | 来源标签 | 映射期刊 | 论文 | 范围 |",
        "|---|---|---|---|---|",
    ]
    for item in summary["missing_china_like"][:50]:
        lines.append(
            f"| {item.get('date') or ''} | {item.get('journal') or ''} | "
            f"{item.get('mapped_journal') or ''} | {md_link(item)} | {item.get('scope_bucket') or ''} |"
        )
    if not summary["missing_china_like"]:
        lines.append("|  |  |  | 暂无 |  |")

    return "\n".join(lines) + "\n"


def main() -> None:
    remote_payload = fetch_json(ALO_API)
    papers = [item for item in remote_payload.get("papers", []) if isinstance(item, dict)]
    titles, dois = local_keys(local_records())
    known_names = monitor_names()

    missing: list[dict[str, Any]] = []
    matched = 0
    for paper in papers:
        title = norm_title(str(paper.get("title") or ""))
        doi = doi_from_url(str(paper.get("link") or ""))
        if title in titles or (doi and doi in dois):
            matched += 1
            continue
        journal_label = str(paper.get("journal") or "")
        mapped = ALIASES.get(journal_label, journal_label)
        missing.append(
            {
                "date": paper.get("date"),
                "first_seen_at": paper.get("fdate"),
                "journal": journal_label,
                "mapped_journal": mapped,
                "in_monitor_list": norm_title(mapped) in known_names,
                "scope_bucket": scope_bucket(mapped, norm_title(mapped) in known_names),
                "china_like": is_china_like(paper),
                "title": paper.get("title"),
                "author": paper.get("author"),
                "link": paper.get("link"),
                "tier": paper.get("tier"),
                "reason": likely_gap_reason(journal_label, mapped, paper.get("link")),
            }
        )

    missing_in_monitor = [item for item in missing if item["scope_bucket"] == "our_scope"]
    missing_econ_expand = [item for item in missing if item["scope_bucket"] == "econ_expand_candidate"]
    missing_broader_relevant = [item for item in missing if item["scope_bucket"] == "broader_relevant_candidate"]
    broader_out = [item for item in missing if item["scope_bucket"] == "broader_out_of_scope"]
    summary = {
        "source": ALO_API,
        "alo_count": len(papers),
        "matched_local_daily": matched,
        "possible_missing_count": len(missing),
        "missing_china_like_count": sum(1 for item in missing if item["china_like"]),
        "missing_in_monitor_list_count": len(missing_in_monitor),
        "missing_econ_expand_count": len(missing_econ_expand),
        "missing_broader_relevant_count": len(missing_broader_relevant),
        "broader_out_of_scope_count": len(broader_out),
        "missing_by_journal": Counter(item["journal"] for item in missing).most_common(50),
        "missing_china_like": [item for item in missing if item["china_like"]][:50],
        "missing_in_monitor_list": missing_in_monitor[:120],
        "missing_econ_expand": missing_econ_expand[:120],
        "missing_broader_relevant": missing_broader_relevant[:120],
        "broader_out_of_scope_by_journal": Counter(item["journal"] for item in broader_out).most_common(50),
        "missing_sample": missing[:50],
    }
    write_json(OUT_PATH, summary)
    MD_OUT_PATH.write_text(render_markdown(summary), encoding="utf-8")
    print(
        "alohomora coverage: "
        f"alo={summary['alo_count']} matched={summary['matched_local_daily']} "
        f"missing={summary['possible_missing_count']} "
        f"china_like={summary['missing_china_like_count']} "
        f"in_monitor_list={summary['missing_in_monitor_list_count']} "
        f"econ_expand={summary['missing_econ_expand_count']} "
        f"broader_relevant={summary['missing_broader_relevant_count']} "
        f"broader_out={summary['broader_out_of_scope_count']}"
    )
    print(OUT_PATH)
    print(MD_OUT_PATH)


if __name__ == "__main__":
    main()
