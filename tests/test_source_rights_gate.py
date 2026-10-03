from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys
from typing import Final

import pytest

from tistory_growth_os.contracts.json_ast import JsonObject, JsonString
from tistory_growth_os.contracts.json_decode import parse_json, parse_json_file
from tistory_growth_os.contracts.registry import ContractRegistry
from tistory_growth_os.domain.content_request_decode import decode_offline_run_request
from tistory_growth_os.artifacts.serialization import source_evidence_json
from tistory_growth_os.domain.results import PipelineBlocked
from tistory_growth_os.pipeline.evidence import parse_canonical_input_digest
from tistory_growth_os.pipeline.orchestrator import run_offline_pipeline
from tistory_growth_os.pipeline._quality_sources import source_rights_findings


ROOT: Final = Path(__file__).resolve().parents[1]


def held_source_input() -> str:
    return (ROOT / "tests/fixtures/topic_supported.json").read_text().replace(
        '"link_and_paraphrase"', '"review_required"', 1,
    )


def test_pending_rights_is_a_valid_source_state_not_a_malformed_request() -> None:
    # Given: a structurally complete source with an unresolved rights review.
    value = parse_json(held_source_input())
    registry = ContractRegistry.load(ROOT / "contracts")
    # When: the current request schema is applied.
    issues = registry.validate("offline-run-request", value)
    # Then: review is a domain state, not a parse error.
    assert issues == ()


def test_pending_rights_blocks_pipeline_despite_supported_claims() -> None:
    # Given: linked claims whose source review is still pending.
    request = decode_offline_run_request(parse_json(held_source_input()))
    # When: the real offline pipeline evaluates the request.
    result = run_offline_pipeline(ROOT, request, parse_canonical_input_digest("a" * 64))
    # Then: a policy finding prevents a ready/rendered result.
    assert isinstance(result, PipelineBlocked)
    assert result.reason_codes == ("POLICY_EVIDENCE_REQUIRED",)
    assert result.quality_report.findings[0].path == "/source_evidence/0/license_status"
    assert result.quality_report.claim_evidence_coverage == 1


def test_cli_pending_rights_writes_only_schema_valid_diagnostics(tmp_path: Path) -> None:
    # Given: isolated contracts and a pending-rights request.
    _ = shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    _ = (tmp_path / "request.json").write_text(held_source_input())
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    # When: the real executable receives the request.
    result = subprocess.run(
        [sys.executable, "-m", "tistory_growth_os", "run", "--root", str(tmp_path),
         "--fixture", "request.json", "--output", "output", "--dry-run"],
        capture_output=True, text=True, check=False, env=environment, timeout=15,
    )
    # Then: no approval bundle is written and reports retain the blocking reason.
    assert result.returncode == 2
    assert result.stdout == ""
    payload = parse_json(result.stderr)
    assert isinstance(payload, JsonObject)
    assert payload.get("status") == JsonString("blocked")
    assert payload.get("result_code") == JsonString("POLICY_EVIDENCE_REQUIRED")
    paths = {p.relative_to(tmp_path / "output").as_posix()
             for p in (tmp_path / "output").rglob("*") if p.is_file()}
    assert paths == {"diagnostics/audit.jsonl", "diagnostics/quality-report.json",
                     "diagnostics/run-report.json", "diagnostics/article-draft.json"}
    registry = ContractRegistry.load(tmp_path / "contracts")
    for name in ("quality-report", "run-report", "article-draft"):
        assert registry.validate(name, parse_json_file(
            tmp_path / "output/diagnostics" / f"{name}.json",
        )) == ()
    draft = parse_json_file(tmp_path / "output/diagnostics/article-draft.json")
    assert isinstance(draft, JsonObject)
    assert draft.get("quality_status") == JsonString("blocked")


@pytest.mark.parametrize("status", ["", "approved_by_magic"])
def test_unknown_rights_values_still_fail_schema_validation(status: str) -> None:
    # Given: a source with an unsupported status.
    raw = held_source_input().replace('"review_required"', f'"{status}"')
    # When: the schema evaluates this input.
    issues = ContractRegistry.load(ROOT / "contracts").validate(
        "offline-run-request", parse_json(raw),
    )
    # Then: unknown states cannot be interpreted as permission.
    assert any(issue.pointer == "/source_evidence/0/license_status" for issue in issues)


def test_pending_source_round_trips_through_standalone_schema() -> None:
    # Given: a parsed pending-rights source.
    request = decode_offline_run_request(parse_json(held_source_input()))
    # When: the domain source is serialized.
    value = source_evidence_json(request.evidence[0])
    # Then: the source schema preserves the hold rather than dropping it.
    assert value.get("license_status") == JsonString("review_required")
    assert ContractRegistry.load(ROOT / "contracts").validate("source-evidence", value) == ()


@pytest.mark.parametrize("status", ["link_and_paraphrase", "quoted_with_limit", "owner_provided"])
def test_existing_usage_labels_do_not_gain_a_pending_rights_finding(status: str) -> None:
    # Given: an existing declared source-use label.
    raw = held_source_input().replace('"review_required"', f'"{status}"')
    request = decode_offline_run_request(parse_json(raw))
    # When: only the source-rights hold gate is evaluated.
    findings = source_rights_findings(request.evidence)
    # Then: no new pending-review finding is introduced.
    assert findings == ()


def test_synthetic_input_is_schema_valid_and_preserves_both_holds() -> None:
    # Given: a synthetic input with two unresolved source-rights decisions.
    value = parse_json_file(ROOT / "tests/fixtures/topic_rights_pending.json")
    # When: schema and typed source-rights contracts are evaluated.
    issues = ContractRegistry.load(ROOT / "contracts").validate("offline-run-request", value)
    findings = source_rights_findings(decode_offline_run_request(value).evidence)
    # Then: both source holds survive contract validation.
    assert issues == ()
    assert {finding.path for finding in findings} == {
        "/source_evidence/0/license_status", "/source_evidence/1/license_status",
    }
