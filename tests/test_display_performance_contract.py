from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _manifest_for(output: Path, relative: str) -> tuple[str, dict]:
    page_path = output / relative
    html = page_path.read_text(encoding="utf-8")
    match = re.search(r'data-lazy-manifest="([^"]+)"', html)
    assert match, relative
    manifest_path = (page_path.parent / match.group(1)).resolve()
    return html, json.loads(manifest_path.read_text(encoding="utf-8"))


def test_large_pages_use_scoped_shards_and_keep_repository_boundaries(tmp_path):
    data_hash_before = _tree_hash(ROOT / "data")
    classic_hash_before = _tree_hash(ROOT / "docs" / "classic")
    output = tmp_path / "docs"
    subprocess.run(
        [sys.executable, "scripts/render_site.py", "--docs-dir", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert _tree_hash(ROOT / "data") == data_hash_before
    assert _tree_hash(ROOT / "docs" / "classic") == classic_hash_before
    assert not (output / "paper-index.json").exists()

    pages = (
        ("search/index.html", 500_000),
        ("working-papers/index.html", 750_000),
        ("topics/china/index.html", 750_000),
    )
    manifests: dict[str, dict] = {}
    for relative, size_limit in pages:
        html, manifest = _manifest_for(output, relative)
        manifests[relative] = manifest
        assert len(html.encode("utf-8")) <= size_limit, relative
        assert html.count('<article class="event"') <= 40, relative
        assert {"version", "count", "shards"} <= set(manifest), relative
        assert "html" not in manifest, relative
        assert len(json.dumps(manifest, ensure_ascii=False)) < 20_000, relative
        assert manifest["count"] >= 0, relative

    search_html = (output / "search" / "index.html").read_text(encoding="utf-8")
    assert 'data-lazy-defer="true"' in search_html
    assert manifests["search/index.html"]["count"] >= manifests["working-papers/index.html"]["count"]
    assert manifests["search/index.html"]["count"] >= manifests["topics/china/index.html"]["count"]

    for shard_path in (output / "paper-index").glob("*/shards/*.json"):
        shard = json.loads(shard_path.read_text(encoding="utf-8"))
        assert len(shard) <= 40
        assert all({"key", "html", "search"} <= set(item) for item in shard)
        assert all("__BASE__" not in item["html"] for item in shard)
        assert all("__PAPER_BASE__/paper.html?key=" in item["html"] for item in shard)

    for route_path in (output / "paper-index").glob("*/route/*.json"):
        route = json.loads(route_path.read_text(encoding="utf-8"))
        assert isinstance(route, list)
        assert all({"key", "shard"} <= set(item) for item in route)


def test_runtime_contract_defers_search_and_loads_only_requested_shards():
    renderer = (ROOT / "scripts" / "render_site.py").read_text(encoding="utf-8")
    assert "len(public) > 40" in renderer
    assert "LAZY_SHARD_SIZE = 40" in renderer
    assert "data-lazy-defer" in renderer
    assert "if (list.dataset.lazyDefer !== 'true' || hasPreset)" in renderer
    assert "route/" in renderer
    assert "shards/" in renderer
    assert "queryTokens" in renderer
    assert "batchSize = 40" in renderer
    assert 'docs_dir / "paper-index.json"' not in renderer
