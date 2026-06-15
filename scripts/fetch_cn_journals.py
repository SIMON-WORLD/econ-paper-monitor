"""Fetch official Chinese journal article records.

The Chinese journal sites are heterogeneous and several do not expose RSS.
This module therefore uses conservative, site-specific parsers. A record is
kept only when it looks like a real article detail page or official TOC item.

Date policy:
- available_online: exact online/first-published date from official source.
- published_online: exact official publication date when available.
- source_issue: issue/page string when the site only exposes issue metadata.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from common import DATA_DIR, fetch_text, load_journals, now_iso, today_str, write_json
from status import record_source


CN_HOME_URLS = {
    "journal-f69300dae2": "https://zgncjj.ajcass.com/#/",
    "journal-679eaa2a0c": "https://sjjj.magtech.com.cn/CN/home",
    "journal-ba9f46c919": "https://erj.ajcass.com/#/",
    "journal-379b4022ce": "https://glsj.chinajournal.net.cn/WKB/WebPublication/index.aspx?mid=glsj",
    "journal-bf2aa9381f": "http://ciejournal.ajcass.com/?jumpnotice=201606280001",
    "journal-edcb877d78": "https://www.jqte.net/sljjjsjjyj/ch/index.aspx",
}

AJCASS_JOURNAL_IDS = {
    "journal-f69300dae2": "201606270007",
    "journal-ba9f46c919": "201606270001",
}

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
    "复现包",
    "补充材料",
    "期刊征文",
    "公告",
    "通知",
    "目录",
)


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def decode_payload(payload: bytes, charset: str | None = None) -> str:
    candidates = []
    if charset:
        candidates.append(charset)
    candidates.extend(["utf-8", "gb18030", "gbk"])
    for candidate in dict.fromkeys(candidates):
        try:
            return payload.decode(candidate)
        except Exception:
            continue
    return payload.decode("utf-8", errors="replace")


def fetch_text_partial(url: str, timeout: int = 25, max_bytes: int = 300_000) -> str:
    """Read enough HTML for TOC parsing without letting slow sites stall."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    contexts = [None]
    if url.startswith("https://"):
        contexts.append(ssl._create_unverified_context())
    last_error: Exception | None = None
    for context in contexts:
        payload = bytearray()
        charset = None
        try:
            open_kwargs = {"timeout": timeout}
            if context is not None:
                open_kwargs["context"] = context
            with urllib.request.urlopen(request, **open_kwargs) as response:  # type: ignore[arg-type]
                charset = response.headers.get_content_charset()
                while len(payload) < max_bytes:
                    try:
                        chunk = response.read(min(65536, max_bytes - len(payload)))
                    except (TimeoutError, socket.timeout):
                        break
                    if not chunk:
                        break
                    payload.extend(chunk)
            if payload:
                return decode_payload(bytes(payload), charset)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if payload:
                return decode_payload(bytes(payload), charset)
    if last_error:
        raise last_error
    return ""


def clean_title(value: str | None) -> str:
    value = clean_text(value)
    value = re.sub(r"^(摘要|Abstract|论文|标题)[:：]\s*", "", value, flags=re.I)
    return value.strip(" -_|\u3000")


def has_chinese(value: str | None) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value or "")


def is_noise_title(title: str) -> bool:
    return len(title) < 4 or any(word in title for word in NOISE_TEXT)


def normalize_url(url: str, base_url: str) -> str:
    return urllib.parse.urljoin(base_url, html.unescape(url)).split("#", 1)[0]


def extract_date(text: str) -> str | None:
    patterns = [
        r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?",
        r"(20\d{2})(\d{2})(\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if not match:
            continue
        try:
            year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            return f"{year:04d}-{month:02d}-{day:02d}"
        except ValueError:
            return None
    return None


def first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def make_record(
    journal: dict[str, Any],
    title: str,
    url: str,
    *,
    authors: list[str] | None = None,
    abstract: str | None = None,
    available_online: str | None = None,
    published_online: str | None = None,
    source_issue: str | None = None,
    date_source: str = "issue_only",
    source_url: str | None = None,
    doi: str | None = None,
) -> dict[str, Any] | None:
    title = clean_title(title)
    if is_noise_title(title):
        return None
    doi = doi.strip() if doi else None
    if doi and not doi.lower().startswith("10."):
        doi = None
    return {
        "title": title,
        "title_zh": title if has_chinese(title) else None,
        "abstract": clean_text(abstract) or None,
        "abstract_zh": clean_text(abstract) if has_chinese(abstract) else None,
        "authors": authors or [],
        "journal": journal["title"],
        "journal_short": journal.get("short_name"),
        "journal_id": journal["id"],
        "source_type": "journal",
        "source": "cn-official",
        "source_url": source_url or url,
        "publisher": journal.get("publisher"),
        "published_online": published_online,
        "available_online": available_online,
        "source_issue": source_issue,
        "date_source": date_source,
        "detected_at": now_iso(),
        "doi": doi,
        "url": url,
        "pdf_url": None,
        "fields": journal.get("fields", []),
        "ai_tags": [],
        "translation_status": "native_chinese" if has_chinese(title) else "missing_title",
    }


def parse_meta(html_text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for tag in re.findall(r"<meta\b[^>]*>", html_text, flags=re.I):
        key_match = re.search(r"(?:name|property)=['\"]([^'\"]+)['\"]", tag, flags=re.I)
        content_match = re.search(r"content=['\"]([^'\"]*)['\"]", tag, flags=re.I)
        if key_match and content_match:
            meta[key_match.group(1).lower()] = html.unescape(content_match.group(1)).strip()
    return meta


def parse_detail_meta(html_text: str) -> tuple[str | None, list[str], str | None, str | None, str | None]:
    meta = parse_meta(html_text)
    title = first_nonempty(
        meta.get("citation_title"),
        meta.get("dc.title"),
        meta.get("og:title"),
        clean_text(re.search(r"<title[^>]*>([\s\S]*?)</title>", html_text, flags=re.I).group(1))
        if re.search(r"<title[^>]*>([\s\S]*?)</title>", html_text, flags=re.I)
        else None,
    )
    authors = [value for key, value in meta.items() if key.startswith("citation_author") and value]
    doi = first_nonempty(meta.get("citation_doi"), meta.get("dc.identifier"), meta.get("doi"))
    online = first_nonempty(meta.get("citation_online_date"), meta.get("article:published_time"))
    published = first_nonempty(meta.get("citation_publication_date"), meta.get("dc.date"))
    return title, authors, doi, extract_date(online or ""), extract_date(published or "")


def split_authors(value: str | None) -> list[str]:
    text = clean_text(value)
    text = re.sub(r"^\[|\]$", "", text)
    if not text:
        return []
    return [item.strip() for item in re.split(r"[，,;；、]\s*", text) if item.strip()]


def parse_world_economy(html_text: str, journal: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    base_url = CN_HOME_URLS[journal["id"]]
    blocks = re.findall(r'<li[^>]+id=["\']art\d+["\'][\s\S]*?</li>', html_text, flags=re.I)
    records: list[dict[str, Any]] = []
    for block in blocks:
        title_match = re.search(r'class=["\']j-title-1["\'][\s\S]*?<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', block, flags=re.I)
        if not title_match:
            continue
        href, title_html = title_match.groups()
        url = normalize_url(href, base_url)
        if "/CN/Y" not in url:
            continue
        authors_match = re.search(r'class=["\']j-author["\'][^>]*>([\s\S]*?)</div>', block, flags=re.I)
        issue_match = re.search(r'class=["\']j-volumn["\'][^>]*>([\s\S]*?)</span>', block, flags=re.I)
        abstract_match = re.search(r'class=["\']j-abstract["\'][^>]*>([\s\S]*?)</div>', block, flags=re.I)
        record = make_record(
            journal,
            clean_title(title_html),
            url,
            authors=split_authors(authors_match.group(1) if authors_match else None),
            abstract=abstract_match.group(1) if abstract_match else None,
            source_issue=clean_text(issue_match.group(1)) if issue_match else None,
            date_source="issue_only",
            source_url=base_url,
        )
        if record:
            records.append(record)
        if len(records) >= limit:
            break
    return records


def parse_jqte(html_text: str, journal: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    base_url = CN_HOME_URLS[journal["id"]]
    matches = re.findall(
        r'<a[^>]+href=["\']([^"\']*reader/view_abstract\.aspx\?file_no=[^"\']+)["\'][^>]*>([\s\S]*?)</a>([\s\S]{0,900})',
        html_text,
        flags=re.I,
    )
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for href, title_html, tail in matches:
        url = normalize_url(href, base_url)
        if url in seen:
            continue
        seen.add(url)
        authors_match = re.search(r"<span[^>]*>\s*(?:\[|【)([\s\S]*?)(?:\]|】)\s*</span>", tail, flags=re.I)
        issue_match = re.search(r"<em[^>]*>([\s\S]*?)</em>", tail, flags=re.I)
        record = make_record(
            journal,
            clean_title(title_html),
            url,
            authors=split_authors(authors_match.group(1) if authors_match else None),
            source_issue=clean_text(issue_match.group(1)) if issue_match else None,
            date_source="issue_only",
            source_url=base_url,
        )
        if record:
            records.append(record)
        if len(records) >= limit:
            break
    return records


def parse_cie(html_text: str, journal: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    base_url = CN_HOME_URLS[journal["id"]]
    main = html_text
    marker = main.find("当期目录")
    if marker >= 0:
        main = main[marker : marker + 50000]
    matches = re.findall(r'<a[^>]+href=["\']([^"\']*Magazine/Show\?id=\d+[^"\']*)["\'][^>]*>([\s\S]*?)</a>([\s\S]{0,1600})', main, flags=re.I)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for href, title_html, tail in matches:
        url = normalize_url(href, base_url)
        if url in seen:
            continue
        seen.add(url)
        text_tail = clean_text(tail)
        issue_match = re.search(r"(20\d{2}\s*年,\s*第\s*\d+\s*期[:：]\s*\d+\s*-\s*\d+\s*页)", text_tail)
        author_text = text_tail.split("20", 1)[0]
        record = make_record(
            journal,
            clean_title(title_html),
            url,
            authors=split_authors(author_text),
            source_issue=clean_text(issue_match.group(1)) if issue_match else None,
            date_source="issue_only",
            source_url=base_url,
        )
        if record:
            records.append(record)
        if len(records) >= limit:
            break
    return records


class SimpleLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href:
            text = clean_title("".join(self._text))
            if text:
                self.links.append((self._href, text))
            self._href = None
            self._text = []


def fetch_json_api(path: str, params: dict[str, str], timeout: int = 6) -> Any:
    url = "https://api.ajcass.com/api/" + path.lstrip("/")
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))


def walk_json(value: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if any(key.lower() in {"title", "papertitle", "name", "subject"} for key in value):
            items.append(value)
        for child in value.values():
            items.extend(walk_json(child))
    elif isinstance(value, list):
        for child in value:
            items.extend(walk_json(child))
    return items


def parse_ajcass_api(journal: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    journal_id = AJCASS_JOURNAL_IDS[journal["id"]]
    endpoints = [
        "Article/Search",
        "Article/GetArticleList",
        "Journal/GetArticleList",
        "Paper/GetList",
        "Article/GetList",
        "Content/GetList",
    ]
    param_sets = [
        {"JournalID": journal_id, "PageIndex": "1", "PageSize": str(limit)},
        {"JournalID": journal_id, "page": "1", "limit": str(limit)},
        {"JournalID": journal_id, "pageIndex": "1", "pageSize": str(limit)},
    ]
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for endpoint in endpoints:
        for params in param_sets:
            try:
                payload = fetch_json_api(endpoint, params)
            except Exception:
                continue
            for item in walk_json(payload):
                title = first_nonempty(
                    str(item.get("Title")) if item.get("Title") else None,
                    str(item.get("PaperTitle")) if item.get("PaperTitle") else None,
                    str(item.get("Name")) if item.get("Name") else None,
                    str(item.get("Subject")) if item.get("Subject") else None,
                )
                if not title:
                    continue
                content_id = first_nonempty(
                    str(item.get("ContentID")) if item.get("ContentID") else None,
                    str(item.get("ID")) if item.get("ID") else None,
                    str(item.get("ArticleID")) if item.get("ArticleID") else None,
                )
                url = CN_HOME_URLS[journal["id"]]
                if content_id:
                    url = f"{url.rstrip('/')}/#/detail?id={urllib.parse.quote(content_id)}"
                if url in seen:
                    continue
                seen.add(url)
                issue = first_nonempty(
                    str(item.get("IssueName")) if item.get("IssueName") else None,
                    str(item.get("YearIssue")) if item.get("YearIssue") else None,
                    str(item.get("Issue")) if item.get("Issue") else None,
                )
                date_text = first_nonempty(
                    str(item.get("PublishDate")) if item.get("PublishDate") else None,
                    str(item.get("CreateTime")) if item.get("CreateTime") else None,
                    str(item.get("OnlineDate")) if item.get("OnlineDate") else None,
                )
                date_value = extract_date(date_text or "")
                record = make_record(
                    journal,
                    title,
                    url,
                    authors=split_authors(first_nonempty(str(item.get("Author")) if item.get("Author") else None, str(item.get("Authors")) if item.get("Authors") else None)),
                    abstract=first_nonempty(str(item.get("Summary")) if item.get("Summary") else None, str(item.get("Abstract")) if item.get("Abstract") else None),
                    available_online=date_value if item.get("OnlineDate") else None,
                    published_online=date_value if date_value and not item.get("OnlineDate") else None,
                    source_issue=issue,
                    date_source="ajcass_api",
                    source_url=CN_HOME_URLS[journal["id"]],
                )
                if record:
                    records.append(record)
                if len(records) >= limit:
                    return records
            if records:
                return records
    return records


def fetch_glsj(journal: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    # This site currently returns a validation/login page for anonymous AJAX
    # calls from Actions. Keep this parser strict to avoid treating news/nav
    # links as papers.
    base = "https://glsj.chinajournal.net.cn/WKB/WebPublication/"
    endpoints = [
        "getFirstPublishPaperInfo.ashx",
        "getThisIssuePaperInfo.ashx?y=2026&i=5",
    ]
    records: list[dict[str, Any]] = []
    for endpoint in endpoints:
        try:
            page = fetch_text(base + endpoint, timeout=15)
        except Exception:
            continue
        if "showValidateCode" in page or "login.css" in page:
            continue
        parser = SimpleLinkParser()
        parser.feed(page)
        for href, title in parser.links:
            if is_noise_title(title):
                continue
            url = normalize_url(href, base)
            if "Paper" not in url and "Content" not in url and "Article" not in url:
                continue
            record = make_record(journal, title, url, source_url=base + endpoint)
            if record:
                records.append(record)
            if len(records) >= limit:
                return records
    return records


def fetch_journal(journal: dict[str, Any], url: str, limit: int) -> tuple[list[dict[str, Any]], str]:
    journal_id = journal["id"]
    if journal_id in AJCASS_JOURNAL_IDS:
        records = parse_ajcass_api(journal, limit)
        return records, "ajcass-api" if records else "ajcass-api-empty"
    if journal_id == "journal-379b4022ce":
        records = fetch_glsj(journal, limit)
        return records, "glsj-ajax" if records else "glsj-ajax-empty"

    html_text = fetch_text_partial(url, timeout=25)
    if journal_id == "journal-679eaa2a0c":
        return parse_world_economy(html_text, journal, limit), "magtech-toc"
    if journal_id == "journal-edcb877d78":
        return parse_jqte(html_text, journal, limit), "jqte-toc"
    if journal_id == "journal-bf2aa9381f":
        return parse_cie(html_text, journal, limit), "cie-toc"
    return [], "unsupported"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journals", type=Path, default=DATA_DIR / "journals.yml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit-per-journal", type=int, default=20)
    parser.add_argument("--only", action="append", default=[])
    args = parser.parse_args()

    journals_by_id = {journal["id"]: journal for journal in load_journals(args.journals)}
    output = args.output or DATA_DIR / "raw" / "cn" / f"{today_str()}.json"
    records: list[dict[str, Any]] = []
    messages: list[str] = []

    selected_urls = CN_HOME_URLS
    if args.only:
        selected = set(args.only)
        selected_urls = {key: value for key, value in CN_HOME_URLS.items() if key in selected}

    for journal_id, url in selected_urls.items():
        journal = journals_by_id.get(journal_id)
        if not journal:
            messages.append(f"{journal_id}: missing journal config")
            continue
        try:
            fetched, mode = fetch_journal(journal, url, args.limit_per_journal)
            records.extend(fetched)
            messages.append(f"{journal_id}: {len(fetched)} via {mode}")
        except Exception as exc:  # noqa: BLE001
            messages.append(f"{journal_id}: error {type(exc).__name__}: {exc}")

    write_json(output, records)
    ok = any(not msg.endswith("empty") for msg in messages) and bool(records)
    record_source("cn-journals", ok=ok, count=len(records), message="; ".join(messages))
    print(f"wrote {len(records)} Chinese journal records to {output}")
    for message in messages:
        print(message)


if __name__ == "__main__":
    main()
