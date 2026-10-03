from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
from typing import Final

import pytest

from tests.review_support import approve_fixture
from tistory_growth_os.commands.cli import main
from tistory_growth_os.contracts.json_ast import JsonNumber, JsonObject, JsonString
from tistory_growth_os.contracts.json_decode import parse_json


ROOT: Final = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case", [
    ("missing", "REVIEW_REQUIRED"),
    ("expired", "REVIEW_EXPIRED"),
    ("malformed", "REVIEW_INVALID"),
])
def test_cli_review_failure_exposes_audit_without_bundle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: tuple[str, str],
) -> None:
    # Given: a synthetic request with no usable review in an isolated project.
    kind, expected = case
    _ = shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    fixture = tmp_path / "input.json"
    _ = shutil.copyfile(ROOT / "tests/fixtures/topic_supported.json", fixture)
    if kind != "missing":
        subject = approve_fixture(tmp_path, fixture, datetime.now(timezone.utc) - timedelta(days=1))
        if kind == "malformed":
            _ = (tmp_path / f"contracts/reviews/{subject.digest}.json").write_text("{")
    # When: the real CLI runs with its operational clock and no approval bypass.
    code = main(("run", "--root", str(tmp_path), "--fixture", "input.json",
                 "--output", "output", "--dry-run"))
    captured = capsys.readouterr()
    payload = parse_json(captured.err)
    assert isinstance(payload, JsonObject)
    # Then: a discoverable audit explains the block and no package is created.
    assert code == 2
    assert captured.out == ""
    assert payload.get("result_code") == JsonString(expected)
    assert payload.get("external_write_count") == JsonNumber(0)
    assert payload.get("artifact_path") == JsonString("output/review-audit.jsonl")
    assert (tmp_path / "output/review-audit.jsonl").is_file()
    assert not (tmp_path / "output/bundle").exists()
