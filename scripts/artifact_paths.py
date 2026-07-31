"""Path sanitisation for artifacts committed to the public repository.

Everything under ``data/`` is committed and publicly readable, so a path that
reaches an artifact must never describe a machine. Two shapes have actually
leaked: the operator's Windows path (``E:\\BaiduSyncdisk\\...``) from the local
CNKI supplement, and the CI runner path (``/home/runner/work/...``) from the
hosted pipeline.

Kept as its own module so both the data line and the display line can use it
without either importing the other.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Record fields that are known to carry a file path.
PATH_FIELDS = ("_raw_file", "raw_file", "source_file")

# A Windows drive letter or a UNC share. The negative lookbehind keeps URL
# schemes ("https://") from matching.
_WINDOWS_PATH = re.compile(r"^(?:(?<![A-Za-z])[A-Za-z]:[\\/]|\\\\)")


def _basename(text: str) -> str:
    return text.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def repo_relative_path(path: Any) -> str:
    """Return a repository-relative POSIX path, or a bare file name."""
    text = str(path)
    parsed = Path(text)
    if _WINDOWS_PATH.match(text) and not parsed.is_absolute():
        return _basename(text)
    try:
        candidate = parsed.resolve()
        # On Windows, a path inside this checkout is still a legitimate
        # repository-relative artifact path. Check containment before the
        # generic drive-letter sanitizer below.
        return candidate.relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        # A Windows path handled on POSIX is not recognised as absolute, so
        # ``resolve()`` would anchor it inside the repository and defeat the
        # sanitisation. Reduce those before returning the fallback.
        return _basename(text)


def sanitize_record_paths(records: Any) -> int:
    """Rewrite path fields of already-persisted records, in place.

    Artifacts that merge with their previous content carry a leaked path
    forward forever once one is written, so they are healed on every write
    rather than only at production time. Returns the number of fields that
    were rewritten, so a caller can persist a heal-only change.
    """
    if not isinstance(records, list):
        return 0
    changed = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        for field in PATH_FIELDS:
            value = record.get(field)
            if isinstance(value, str) and value:
                cleaned = repo_relative_path(value)
                if cleaned != value:
                    record[field] = cleaned
                    changed += 1
    return changed
