from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from tistory_growth_os.artifacts.diagnostics import (
    write_blocked_diagnostics,
    write_invalid_diagnostics,
)
from tistory_growth_os.artifacts import diagnostics as diagnostic_writer
from tistory_growth_os.contracts.json_decode import (
    ContractIssue,
    JsonDecodeError,
    parse_json_file,
)
from tistory_growth_os.contracts.json_encode import encode_json_bytes
from tistory_growth_os.contracts.json_ast import JsonObject, JsonString
from tistory_growth_os.contracts.registry import ContractRegistry
from tistory_growth_os.artifacts.serialization import article_draft_json
from tistory_growth_os.domain.content_request_decode import decode_offline_run_request
from tistory_growth_os.domain.results import PipelineBlocked
from tistory_growth_os.pipeline.evidence import parse_canonical_input_digest
from tistory_growth_os.pipeline.orchestrator import run_offline_pipeline


ROOT = Path(__file__).resolve().parents[1]
COMPLETED_AT = datetime.fromisoformat("2026-09-06T09:30:00+09:00")


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    _ = shutil.copytree(ROOT / "contracts", root / "contracts")
    return root


def _blocked() -> PipelineBlocked:
    value = parse_json_file(ROOT / "tests/fixtures/topic_unsupported_claim.json")
    canonical = encode_json_bytes(value)
    request = decode_offline_run_request(value)
    digest = parse_canonical_input_digest(sha256(canonical).hexdigest())
    result = run_offline_pipeline(ROOT, request, digest)
    assert isinstance(result, PipelineBlocked)
    return result


def test_blocked_run_writes_only_structured_diagnostics(tmp_path: Path) -> None:
    root = _project(tmp_path)

    result = write_blocked_diagnostics(
        root,
        "artifacts/blocked",
        _blocked(),
        COMPLETED_AT,
    )

    output = root / "artifacts/blocked/diagnostics"
    assert result.output_path == output
    assert {path.name for path in output.iterdir()} == {
        "audit.jsonl",
        "quality-report.json",
        "run-report.json",
        "article-draft.json",
    }
    report = json.loads((output / "run-report.json").read_text("utf-8"))
    audit = json.loads((output / "audit.jsonl").read_text("utf-8"))
    assert report["status"] == "blocked"
    assert report["result_code"] == "CLAIM_EVIDENCE_REQUIRED"
    assert report["artifact_paths"] == ["quality-report.json", "article-draft.json"]
    assert report["external_write_count"] == 0
    assert audit["bundle_created"] is False
    assert audit["external_write_count"] == 0
    assert not (output.parent / "bundle").exists()
    assert not tuple(output.glob("*.staging-*"))


def test_blocked_diagnostic_preserves_evaluated_draft(tmp_path: Path) -> None:
    # Given: a blocked pipeline result whose actual composed content needs review.
    root = _project(tmp_path)
    blocked = _blocked()
    # When: diagnostic artifacts are written without a rendering step.
    result = write_blocked_diagnostics(root, "artifacts/inspect", blocked, COMPLETED_AT)
    # Then: the schema-valid draft retains its identity, complete content and hold.
    value = parse_json_file(result.output_path / "article-draft.json")
    assert encode_json_bytes(value) == encode_json_bytes(article_draft_json(blocked.draft))
    assert isinstance(value, JsonObject)
    assert value.get("quality_status") == JsonString("blocked")
    assert ContractRegistry.load(root / "contracts").validate("article-draft", value) == ()
    assert not tuple(result.output_path.glob("*.html"))
    assert not (result.output_path.parent / "bundle").exists()


def test_malformed_input_writes_run_report_and_redacted_audit_only(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    malformed = ROOT / "tests/fixtures/topic_malformed.json"
    try:
        _ = parse_json_file(malformed)
    except JsonDecodeError as error:
        issue = error.issue
    else:
        raise AssertionError("fixture must remain malformed")

    result = write_invalid_diagnostics(
        root,
        "artifacts/invalid",
        issue,
        COMPLETED_AT,
    )

    output = result.output_path
    assert {path.name for path in output.iterdir()} == {
        "audit.jsonl",
        "run-report.json",
    }
    report = json.loads((output / "run-report.json").read_text("utf-8"))
    audit_text = (output / "audit.jsonl").read_text("utf-8")
    audit = json.loads(audit_text)
    assert report["status"] == "invalid"
    assert report["result_code"] == "CONTRACT_INVALID"
    assert report["state_history"] == ["invalid"]
    assert report["artifact_paths"] == []
    assert audit["error"]["line"] == issue.line
    assert audit["error"]["column"] == issue.column
    assert audit["bundle_created"] is False
    assert "AKIA" not in audit_text
    assert not (output.parent / "bundle").exists()


def test_invalid_diagnostic_redacts_credential_shaped_error_message(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    marker = "".join(("super", "secret", "value"))
    issue = ContractIssue("/token", "json", "pass" + "word=" + marker)

    result = write_invalid_diagnostics(
        root,
        "artifacts/redacted",
        issue,
        COMPLETED_AT,
    )

    audit = (result.output_path / "audit.jsonl").read_text("utf-8")
    assert marker not in audit
    assert "<redacted>" in audit


def test_injected_diagnostic_replace_failure_leaves_no_staging(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _project(tmp_path)

    def fail_replace(source: Path, destination: Path) -> None:
        _ = source, destination
        raise OSError("injected diagnostic replacement failure")

    monkeypatch.setattr(diagnostic_writer.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected diagnostic replacement failure"):
        _ = write_blocked_diagnostics(
            root,
            "artifacts/failed",
            _blocked(),
            COMPLETED_AT,
        )

    parent = root / "artifacts/failed"
    assert not (parent / "diagnostics").exists()
    assert tuple(parent.glob(".diagnostic-staging-*")) == ()
