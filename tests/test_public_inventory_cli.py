from __future__ import annotations

import json
from pathlib import Path
import shutil

from tistory_growth_os.commands.cli import main


ROOT = Path(__file__).resolve().parents[1]


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    _ = shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "browser-profile",
            ".artifacts",
            ".omo",
            ".pytest_cache",
            "__pycache__",
        ),
    )
    return root


def test_public_inventory_command_classifies_metadata_without_style_content(
    tmp_path: Path,
    capsys,
) -> None:
    # Given
    root = _project(tmp_path)

    # When
    exit_code = main((
        "classify-public-inventory",
        "--root",
        str(root),
        "--input",
        "tests/fixtures/public_inventory_input.json",
        "--output",
        ".artifacts/public-inventory.json",
        "--dry-run",
    ))

    # Then
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    artifact = json.loads(
        (root / ".artifacts/public-inventory.json").read_text(encoding="utf-8")
    )
    assert exit_code == 0
    assert captured.err == ""
    assert payload == artifact
    assert payload["status"] == "pass"
    assert payload["post_count"] == 3
    assert payload["external_write_count"] == 0
    assert payload["summary"]["freshness"] == {
        "review_required": 0,
        "evergreen_review_due": 2,
        "time_sensitive_stale": 1,
    }
    by_title = {post["title"]: post for post in payload["posts"]}
    assert by_title["샘플 의약품 복용 방법과 부작용"]["risk_class"] == "high"
    assert by_title["샘플 경제 개념 안내"]["risk_class"] == "medium"
    assert (
        by_title["2030년 샘플 영화 개봉 일정"][
            "action_candidate"
        ]
        == "refresh_or_retire"
    )
    assert "body" not in json.dumps(payload, ensure_ascii=False)
    assert "description" not in json.dumps(payload, ensure_ascii=False)


def test_public_inventory_command_rejects_duplicate_canonical_url(
    tmp_path: Path,
    capsys,
) -> None:
    # Given
    root = _project(tmp_path)
    source = root / "tests/fixtures/public_inventory_input.json"
    value = json.loads(source.read_text(encoding="utf-8"))
    value["posts"].append(value["posts"][0])
    invalid = root / "tests/fixtures/public_inventory_duplicate.json"
    _ = invalid.write_text(json.dumps(value), encoding="utf-8")

    # When
    exit_code = main((
        "classify-public-inventory",
        "--root",
        str(root),
        "--input",
        "tests/fixtures/public_inventory_duplicate.json",
        "--output",
        ".artifacts/invalid-inventory.json",
        "--dry-run",
    ))

    # Then
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert json.loads(captured.err)["result_code"] == "INVENTORY_INPUT_INVALID"
    assert not (root / ".artifacts/invalid-inventory.json").exists()
