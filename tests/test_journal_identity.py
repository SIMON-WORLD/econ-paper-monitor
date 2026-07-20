from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import load_journals  # noqa: E402


class JournalIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.journals = {item["id"]: item for item in load_journals()}

    def test_journal_of_finance_identity(self) -> None:
        self.assertEqual(self.journals["journal-of-finance"]["issn"], "0022-1082")

    def test_journal_of_law_and_economics_identity(self) -> None:
        self.assertEqual(self.journals["journal-of-law-and-economics"]["issn"], "0022-2186")

    def test_journal_of_agricultural_and_resource_economics_identity(self) -> None:
        self.assertEqual(self.journals["journal-of-agricultural-and-resource-economics"]["issn"], "1068-5502")


if __name__ == "__main__":
    unittest.main()
