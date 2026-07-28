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
        self.assertFalse(record_source.call_args.kwargs["ok"])
        self.assertIn("journals", record_source.call_args.kwargs["details"])

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

    def test_http_200_challenge_page_uses_fallback(self) -> None:
        challenge = mock.MagicMock()
        challenge.read.return_value = b"<html><title>Just a moment...</title></html>"
        challenge.headers.get_content_charset.return_value = "utf-8"
        challenge.__enter__.return_value = challenge
        valid = mock.MagicMock()
        valid.read.return_value = b"<html><title>Forthcoming Papers</title></html>"
        valid.headers.get_content_charset.return_value = "utf-8"
        valid.__enter__.return_value = valid

        with mock.patch.object(
            fetch_priority_toc.urllib.request,
            "urlopen",
            side_effect=[challenge, valid],
        ) as urlopen:
            text = fetch_priority_toc.fetch_toc_text(
                "https://publisher.invalid/toc",
                timeout=5,
                fallback_urls=["https://mirror.invalid/toc"],
            )

        self.assertIn("Forthcoming Papers", text)
        self.assertEqual(urlopen.call_count, 2)

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

    def test_restud_official_homepage_extracts_new_article_links(self) -> None:
        html = """[New ### Macro Shocks and Firm Dynamics with Oligopolistic Financial Intermediaries 24 July 2026 Alessandro T. Villa](https://www.restud.com/macro-shocks-and-firm-dynamics-with-oligopolistic-financial-intermediaries/)"""
        links = fetch_priority_toc.article_links(html, "https://www.restud.com/")
        self.assertEqual(
            links,
            [
                (
                    "https://www.restud.com/macro-shocks-and-firm-dynamics-with-oligopolistic-financial-intermediaries/",
                    "Macro Shocks and Firm Dynamics with Oligopolistic Financial Intermediaries",
                )
            ],
        )

    def test_restud_detail_reads_published_time_and_author_from_jina_page(self) -> None:
        page = """Title: Macro Shocks and Firm Dynamics with Oligopolistic Financial Intermediaries\nPublished Time: 2026-07-24T16:07:56+00:00\nMarkdown Content:\n24 July 2026\n\nAlessandro T. Villa, Federal Reserve Bank of Chicago\n\nAbstract text."""
        with mock.patch.object(fetch_priority_toc, "fetch_toc_text", return_value=page):
            detail = fetch_priority_toc.enrich_detail("https://www.restud.com/example/", "Fallback", 5)
        self.assertEqual(detail["published_online"], "2026-07-24")
        self.assertEqual(detail["authors"], ["Alessandro T. Villa, Federal Reserve Bank of Chicago"])

    def test_restud_author_map_prefers_clean_card_authors(self) -> None:
        html = """<a href="/macro-shocks/"><p class="author-short">Alessandro T. Villa</p></a>"""
        self.assertEqual(
            fetch_priority_toc.restud_author_map(html, "https://www.restud.com/"),
            {"https://www.restud.com/macro-shocks": ["Alessandro T. Villa"]},
        )

    def test_restud_jina_page_extracts_abstract_paragraph(self) -> None:
        page = """Title: Example\nPublished Time: 2026-07-24T16:07:56+00:00\nMarkdown Content:\n24 July 2026\n\nAlessandro T. Villa\n\nMotivated by a secular increase in concentration, I develop a new macroeconomic model with heterogeneous firms and financial intermediaries. The model explains how market power affects investment and aggregate activity during crises."""
        self.assertIn("Motivated by a secular increase", fetch_priority_toc.restud_abstract_from_jina(page))

    def test_priority_journal_status_remains_usable_when_optional_page_is_blocked(self) -> None:
        source = Path(fetch_priority_toc.__file__).read_text(encoding="utf-8")
        self.assertIn('"ok": bool(journal_count)', source)

    def test_partial_harvest_is_not_reported_as_total_source_outage(self) -> None:
        source = Path(fetch_priority_toc.__file__).read_text(encoding="utf-8")
        self.assertIn("ok=failures == 0 or bool(records)", source)


class LocalCnkiLogPathTests(unittest.TestCase):
    def test_status_log_path_is_repo_relative(self) -> None:
        import local_cnki_update

        value = local_cnki_update.log_path_for_status()

        self.assertFalse(Path(value).is_absolute())
        self.assertNotIn(":\\", value)
        self.assertTrue(value.endswith("local-cnki-update.log"))


class AdditionalEconometricSocietyTargetTests(unittest.TestCase):
    def test_forthcoming_targets_cover_configured_journals(self) -> None:
        self.assertIn("theoretical-economics", fetch_priority_toc.TARGETS)
        self.assertIn("quantitative-economics", fetch_priority_toc.TARGETS)
        self.assertEqual(fetch_priority_toc.TARGETS["theoretical-economics"][0]["fallback_issn"], "1933-6837")
        self.assertEqual(fetch_priority_toc.TARGETS["quantitative-economics"][0]["fallback_issn"], "1759-7323")

    def test_oup_advance_targets_cover_crossref_only_oup_journals(self) -> None:
        expected = {
            "quarterly-journal-of-economics",
            "economic-journal",
            "journal-of-the-european-economic-association",
            "journal-of-law-economics-and-organization",
            "review-of-financial-studies",
            "european-review-of-agricultural-economics",
        }
        self.assertTrue(expected.issubset(fetch_priority_toc.TARGETS))
        self.assertTrue(all(fetch_priority_toc.TARGETS[j][0]["kind"] == "oup_advance_articles" for j in expected))

    def test_links_are_filtered_by_journal_doi_prefix(self) -> None:
        html = '<a href="https://doi.org/10.3982/TE9999">A theoretical result</a><a href="https://doi.org/10.3982/QE9999">A quantitative result</a>'
        theoretical = fetch_priority_toc.article_links(
            html,
            "https://www.econometricsociety.org/publications/theoretical-economics/forthcoming-papers",
        )
        quantitative = fetch_priority_toc.article_links(
            html,
            "https://www.econometricsociety.org/publications/quantitative-economics/forthcoming-papers",
        )
        self.assertEqual(len(theoretical), 1)
        self.assertIn("TE9999", theoretical[0][0])
        self.assertEqual(len(quantitative), 1)
        self.assertIn("QE9999", quantitative[0][0])

    def test_econometric_society_cards_extract_primary_pdf_and_authors(self) -> None:
        html = """
        <div class="article" id="forthcoming_Social-Learning">
          <h3 class="article_title">The Social Learning Barrier</h3>
          <p>Brandl, Florian</p>
          <div class="article_actions">
            <a href="/publications/econometrica/forthcoming-papers/0000/00/00/Social-Learning/file/24769-2.pdf">View</a>
            <a href="/publications/econometrica/forthcoming-papers/0000/00/00/Social-Learning/supp/24769SUPP.pdf">Supplemental Appendix</a>
          </div>
        </div>
        """
        base = "https://www.econometricsociety.org/publications/econometrica/forthcoming-papers"
        links = fetch_priority_toc.article_links(html, base)
        authors = fetch_priority_toc.econometric_society_author_map(html, base)
        self.assertEqual(len(links), 1)
        self.assertIn("/file/24769-2.pdf", links[0][0])
        self.assertEqual(links[0][1], "The Social Learning Barrier")
        self.assertEqual(authors[links[0][0]], ["Brandl, Florian"])


if __name__ == "__main__":
    unittest.main()
