import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from sources import registry


def test_discovery_runs_even_when_a_stale_feed_is_configured(monkeypatch, tmp_path):
    registry_path = tmp_path / "source_registry.json"
    registry_path.write_text(
        '{"journals":{"j1":{"rss":[{"url":"https://old.example/feed"}],"sources":[{"type":"homepage","url":"https://example.test/journal"}]}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "REGISTRY_PATH", registry_path)
    source_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    monkeypatch.setattr(registry, "load_registry", lambda path=registry_path: source_registry)
    monkeypatch.setattr(registry, "save_registry", lambda value, path=registry_path: source_registry.update(value))
    monkeypatch.setattr(registry, "configured_rss_urls", lambda journal: [{"url": "https://old.example/feed", "label": "configured"}])
    monkeypatch.setattr(registry, "generated_official_rss_urls", lambda journal: [])
    monkeypatch.setattr(registry, "candidate_pages", lambda journal: ["https://example.test/journal"])
    monkeypatch.setattr(
        registry,
        "discover_feeds_from_page",
        lambda url: [{"url": "https://new.example/feed", "label": "official"}],
    )

    feeds, status = registry.feeds_for_journal({"id": "j1", "sources": [{"type": "rss", "url": "https://old.example/feed"}]}, discover=True)

    assert status == "configured"
    assert {item["url"] for item in feeds} == {"https://old.example/feed", "https://new.example/feed"}
    assert {item["url"] for item in source_registry["journals"]["j1"]["rss"]} == {"https://old.example/feed", "https://new.example/feed"}
