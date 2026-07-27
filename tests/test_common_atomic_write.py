import json
from concurrent.futures import ThreadPoolExecutor

from common import write_json


def test_concurrent_writes_use_independent_temporary_files(tmp_path):
    target = tmp_path / "status.json"

    def write(index):
        write_json(target, {"writer": index, "ok": True})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(32)))

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert 0 <= payload["writer"] < 32
