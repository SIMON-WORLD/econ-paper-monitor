"""Remove obvious Chinese-journal website news/navigation noise."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import DATA_DIR, read_json, write_json


CN_JOURNALS = {
    "journal-379b4022ce",
    "journal-edcb877d78",
    "journal-bf2aa9381f",
    "journal-f69300dae2",
    "journal-679eaa2a0c",
    "journal-ba9f46c919",
}
CN_JOURNAL_NAMES = {"管理世界", "数量经济技术经济研究", "中国工业经济", "中国农村经济", "世界经济", "经济研究"}
ARTICLE_URL_PATTERNS = (
    "reader/view_abstract.aspx?file_no=",
    "view_abstract.aspx?file_no=",
    "sjjj.magtech.com.cn/CN/Y",
    "ciejournal.ajcass.com/Magazine/Show?id=",
    "ajcass.com/#/detail",
    "ajcass.com/#/enDetail",
)
NOISE_TEXT = (
    "平台",
    "数据库",
    "征文",
    "会议",
    "新闻",
    "规范",
    "说明",
    "投稿",
    "采编",
    "影响因子",
    "获评",
    "期刊征文",
    "复现包",
    "补充材料",
    "公告",
    "通知",
    "欢迎订阅",
    "征订",
    "——评《",
)
NOISE_URL = (
    "CommonBlock/SiteContentList",
    "mp.weixin.qq.com",
    "nssd.cn",
    "find.cb.cnki.net",
    ".doc",
    ".docx",
)


def is_article_url(url: str) -> bool:
    return any(pattern.lower() in url.lower() for pattern in ARTICLE_URL_PATTERNS)


def is_noise_record(record: dict[str, Any]) -> bool:
    if record.get("journal_id") not in CN_JOURNALS:
        return False
    title = str(record.get("title") or "")
    url = str(record.get("url") or "")
    if any(noise in title for noise in NOISE_TEXT):
        return True
    if any(noise.lower() in url.lower() for noise in NOISE_URL):
        return True
    if record.get("journal_id") == "journal-edcb877d78" and not record.get("source_issue"):
        return True
    if "#" in url and "ajcass.com/#/" not in url:
        return True
    if is_article_url(url):
        return False
    if record.get("source_issue") and record.get("url"):
        return False
    return not (record.get("available_online") or record.get("published_online"))


def clean_daily(path: Path) -> int:
    records = read_json(path, [])
    kept = [record for record in records if not is_noise_record(record)]
    removed = len(records) - len(kept)
    if removed:
        write_json(path, kept)
    return removed


def clean_seen(path: Path) -> int:
    seen = read_json(path, {"papers": {}})
    papers = seen.setdefault("papers", {})
    removed = []
    for key, value in list(papers.items()):
        title = str(value.get("title") or "")
        journal = str(value.get("journal") or "")
        url = str(value.get("url") or "")
        if journal not in CN_JOURNAL_NAMES:
            continue
        if any(noise in title for noise in NOISE_TEXT):
            removed.append(key)
            continue
        if url and not is_article_url(url):
            removed.append(key)
    for key in removed:
        papers.pop(key, None)
    if removed:
        write_json(path, seen)
    return len(removed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-dir", type=Path, default=DATA_DIR / "daily")
    parser.add_argument("--seen", type=Path, default=DATA_DIR / "seen.json")
    args = parser.parse_args()

    daily_removed = 0
    for path in args.daily_dir.glob("*.json"):
        daily_removed += clean_daily(path)
    seen_removed = clean_seen(args.seen)
    print(f"removed daily={daily_removed} seen={seen_removed}")


if __name__ == "__main__":
    main()
