from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_priority_toc  # noqa: E402


TARGET_COUNT = sum(len(targets) for targets in fetch_priority_toc.TARGETS.values())


class PriorityTocFallbackTests(unittest.TestCase):
    """Guard the Crossref fallback wiring in ``main``.

    The fallback exists because OUP / MIT Press / Econometric Society block CI
    runners. A NameError in the call site disabled it silently: every target
    reported ``0`` and the fallback never ran, so REStud, REStat, and
    Econometrica lost both acquisition paths at once.
    """

    def _run_main(self, fetch_target_mock):
        journals = [{"id": journal_id} for journal_id in fetch_priority_toc.TARGETS]
        timeouts: list[int] = []

        def fake_fallback(journal, target, *, timeout, max_items):
            timeouts.append(timeout)
            return []

        with tempfile.TemporaryDirectory() as tmp:
            argv = [
                "fetch_priority_toc.py",
                "--timeout",
                "7",
                "--output",
                str(Path(tmp) / "priority-toc.json"),
            ]
            with mock.patch.object(fetch_priority_toc, "load_journals", return_value=journals), \
                    mock.patch.object(fetch_priority_toc, "fetch_target", fetch_target_mock), \
                    mock.patch.object(fetch_priority_toc, "fetch_crossref_fallback", fake_fallback), \
                    mock.patch.object(fetch_priority_toc, "record_source") as record_source, \
                    mock.patch.object(sys, "argv", argv):
                fetch_priority_toc.main()

        return timeouts, record_source

    def test_fallback_runs_when_publisher_page_raises(self) -> None:
        timeouts, record_source = self._run_main(
            mock.Mock(side_effect=RuntimeError("blocked-captcha"))
        )

        self.assertEqual(timeouts, [7] * TARGET_COUNT)
        self.assertTrue(record_source.called)

    def test_fallback_runs_when_publisher_page_returns_nothing(self) -> None:
        timeouts, _ = self._run_main(mock.Mock(return_value=[]))

        self.assertEqual(timeouts, [7] * TARGET_COUNT)


class PriorityTocTimeoutScopeTests(unittest.TestCase):
    """Every helper must use its own ``timeout`` parameter, not ``args``.

    Only ``main`` has an ``args`` namespace. A blanket find-replace of
    ``timeout=timeout`` into ``timeout=args.timeout`` turns every helper into a
    NameError at call time, which the CI-blocked publisher endpoints then hide
    behind a one-line status message.
    """

    def test_no_helper_reads_the_args_namespace(self) -> None:
        source = Path(fetch_priority_toc.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        offenders = [
            (node.name, child.lineno)
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name != "main"
            for child in ast.walk(node)
            if isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == "args"
        ]

        self.assertEqual(offenders, [])

    def test_fetch_toc_text_passes_its_own_timeout(self) -> None:
        response = mock.MagicMock()
        response.read.return_value = b"<html>ok</html>"
        response.headers.get_content_charset.return_value = "utf-8"
        response.__enter__.return_value = response

        with mock.patch.object(fetch_priority_toc.urllib.request, "urlopen", return_value=response) as urlopen:
            text = fetch_priority_toc.fetch_toc_text("https://example.invalid/toc", timeout=5)

        self.assertIn("ok", text)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5)

    def test_crossref_fallback_passes_its_own_timeout(self) -> None:
        response = mock.MagicMock()
        response.read.return_value = b'{"message": {"items": []}}'
        response.__enter__.return_value = response
        target = {"kind": "restud_advance", "fallback_issn": "0034-6527"}

        with mock.patch.object(fetch_priority_toc.urllib.request, "urlopen", return_value=response) as urlopen:
            records = fetch_priority_toc.fetch_crossref_fallback(
                {"id": "review-of-economic-studies"}, target, timeout=5, max_items=1
            )

        self.assertEqual(records, [])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 5)


class LocalCnkiLogPathTests(unittest.TestCase):
    def test_status_log_path_is_repo_relative(self) -> None:
        import local_cnki_update

        value = local_cnki_update.log_path_for_status()

        self.assertFalse(Path(value).is_absolute())
        self.assertNotIn(":\\", value)
        self.assertTrue(value.endswith("local-cnki-update.log"))


if __name__ == "__main__":
    unittest.main()
