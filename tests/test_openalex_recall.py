import sys
import json
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from scripts.fetch_openalex_recall import abstract_from_inverted_index, openalex_issn, openalex_get


def test_openalex_issn_keeps_required_hyphen_format():
    assert openalex_issn("00335533") == "0033-5533"
    assert openalex_issn("0033-5533") == "0033-5533"


def test_inverted_index_abstract_is_reconstructed_in_order():
    assert abstract_from_inverted_index({"second": [1], "First": [0], "third": [2]}) == "First second third"


def test_empty_inverted_index_has_no_abstract():
    assert abstract_from_inverted_index({}) is None


def test_openalex_request_retries_transient_transport_failure():
    response = MagicMock()
    response.read.return_value = json.dumps({"results": []}).encode("utf-8")
    response.__enter__.return_value = response
    with patch("scripts.fetch_openalex_recall.urllib.request.urlopen", side_effect=[OSError("EOF"), response]) as opener:
        payload = openalex_get({"filter": "test"}, timeout=1, retries=2)

    assert payload == {"results": []}
    assert opener.call_count == 2
