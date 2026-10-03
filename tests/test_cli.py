from __future__ import annotations

import json
from pathlib import Path
import shutil
from tests.review_support import approve_fixture

import tistory_growth_os.commands.cli as cli_module
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


def test_run_supported_fixture_creates_approval_bundle_and_stdout_json(
    tmp_path: Path,
    capsys,
) -> None:
    root = _project(tmp_path)
    _ = approve_fixture(root, root / "tests/fixtures/topic_supported.json")

    exit_code = main((
        "run",
        "--root",
        str(root),
        "--fixture",
        "tests/fixtures/topic_supported.json",
        "--output",
        ".artifacts/supported",
        "--dry-run",
    ))

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload["status"] == "READY_FOR_APPROVAL"
    assert payload["result_code"] == "READY_FOR_APPROVAL"
    assert payload["package_id"].startswith("package_")
    assert payload["manifest_id"].startswith("manifest_")
    assert payload["bundle_path"] == ".artifacts/supported/bundle"
    assert payload["external_write_count"] == 0
    assert (root / ".artifacts/supported/bundle/article.html").is_file()


def test_run_blocked_fixture_returns_two_and_only_diagnostics(
    tmp_path: Path,
    capsys,
) -> None:
    root = _project(tmp_path)

    exit_code = main((
        "run",
        "--fixture",
        "tests/fixtures/topic_unsupported_claim.json",
        "--output",
        ".artifacts/blocked",
        "--dry-run",
        "--root",
        str(root),
    ))

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    output = root / ".artifacts/blocked/diagnostics"
    assert exit_code == 2
    assert captured.out == ""
    assert payload["status"] == "blocked"
    assert payload["result_code"] == "CLAIM_EVIDENCE_REQUIRED"
    assert payload["external_write_count"] == 0
    assert {path.name for path in output.iterdir()} == {
        "audit.jsonl",
        "quality-report.json",
        "run-report.json",
        "article-draft.json",
    }


def test_run_malformed_fixture_returns_two_without_partial_bundle(
    tmp_path: Path,
    capsys,
) -> None:
    root = _project(tmp_path)

    exit_code = main((
        "run",
        "--root",
        str(root),
        "--fixture",
        "tests/fixtures/topic_malformed.json",
        "--output",
        ".artifacts/invalid",
        "--dry-run",
    ))

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert exit_code == 2
    assert payload["status"] == "invalid"
    assert payload["result_code"] == "CONTRACT_INVALID"
    assert payload["artifact_path"] == ".artifacts/invalid/diagnostics"
    assert not (root / ".artifacts/invalid/bundle").exists()


def test_run_rejects_missing_dry_run_and_unknown_or_duplicate_flags(
    tmp_path: Path,
    capsys,
) -> None:
    root = _project(tmp_path)
    base = (
        "run",
        "--root",
        str(root),
        "--fixture",
        "tests/fixtures/topic_supported.json",
        "--output",
        ".artifacts/no-write",
    )

    assert main(base) == 2
    assert json.loads(capsys.readouterr().err)["result_code"] == "CLI_USAGE_INVALID"
    assert main((*base, "--dry-run", "--wat")) == 2
    assert json.loads(capsys.readouterr().err)["result_code"] == "CLI_USAGE_INVALID"
    assert main((*base, "--dry-run", "--dry-run")) == 2
    assert json.loads(capsys.readouterr().err)["result_code"] == "CLI_USAGE_INVALID"
    assert not (root / ".artifacts/no-write").exists()


def test_audit_project_and_validate_contracts_emit_canonical_json(
    tmp_path: Path,
    capsys,
) -> None:
    root = _project(tmp_path)

    audit_exit = main((
        "audit-project",
        "--root",
        str(root),
        "--json-out",
        ".artifacts/audit.json",
    ))
    audit = json.loads(capsys.readouterr().out)
    validate_exit = main((
        "validate-contracts",
        "--root",
        str(root),
        "--json-out",
        ".artifacts/contracts.json",
    ))
    contracts = json.loads(capsys.readouterr().out)

    assert audit_exit == 0
    assert audit["status"] == "pass"
    assert audit["external_write_count"] == 0
    assert validate_exit == 0
    assert contracts == {
        "contract_count": 18,
        "external_write_count": 0,
        "expected_negative_fixture_count": 1,
        "runtime_contract_count": 12,
        "status": "pass",
        "valid_fixture_count": 3,
    }
    assert json.loads((root / ".artifacts/audit.json").read_text("utf-8")) == audit
    assert json.loads((root / ".artifacts/contracts.json").read_text("utf-8")) == contracts


def test_unexpected_local_failure_does_not_echo_sensitive_exception_text(
    monkeypatch,
    capsys,
) -> None:
    def fail_locally(_argv) -> None:
        raise ValueError("_".join(("api", "key")) + "=must-not-appear")

    monkeypatch.setattr(cli_module, "parse_command_args", fail_locally)

    assert main(("audit-project",)) == 1
    captured = capsys.readouterr()
    assert "must-not-appear" not in captured.err
    assert json.loads(captured.err)["message"] == "unexpected local failure"
