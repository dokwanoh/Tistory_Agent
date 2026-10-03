from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from tistory_growth_os.contracts.json_decode import parse_json
from tistory_growth_os.contracts.registry import ContractRegistry


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/public_inventory_input.json"


def invoke_inventory(payload: str, destination: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "tistory_growth_os", "classify-public-inventory",
         "--root", str(ROOT), "--input", "-", "--output",
         destination.relative_to(ROOT).as_posix(), "--dry-run"],
        input=payload, capture_output=True, text=True, env=environment,
        check=False, timeout=15,
    )


def test_stdin_replay_is_identical_when_source_order_changes() -> None:
    (ROOT / ".artifacts").mkdir(exist_ok=True)
    source = json.loads(FIXTURE.read_text("utf-8"))
    with tempfile.TemporaryDirectory(dir=ROOT / ".artifacts") as temporary:
        destination = Path(temporary) / "inventory.json"
        first = invoke_inventory(json.dumps(source), destination)
        source["posts"].reverse()
        second = invoke_inventory(json.dumps(source), destination)
        assert first.returncode == second.returncode == 0
        assert first.stdout == second.stdout
        assert destination.read_text("utf-8") == first.stdout
        assert ContractRegistry.load(ROOT / "contracts").validate(
            "public-blog-inventory", parse_json(first.stdout),
        ) == ()


def test_malformed_stdin_does_not_overwrite_existing_inventory() -> None:
    (ROOT / ".artifacts").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / ".artifacts") as temporary:
        destination = Path(temporary) / "inventory.json"
        first = invoke_inventory(FIXTURE.read_text("utf-8"), destination)
        second = invoke_inventory('{"posts":', destination)
        assert first.returncode == 0
        assert second.returncode == 2
        assert json.loads(second.stderr)["result_code"] == "INVENTORY_INPUT_INVALID"
        assert destination.read_text("utf-8") == first.stdout
