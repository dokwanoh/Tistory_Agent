from __future__ import annotations

from pathlib import Path

from tistory_growth_os.contracts.json_decode import parse_json_file
from tistory_growth_os.domain.content_request_decode import decode_offline_run_request
from tistory_growth_os.domain.results import PipelineBlocked, PipelineReady
from tistory_growth_os.domain.state import PipelineState
from tistory_growth_os.pipeline.evidence import parse_canonical_input_digest
from tistory_growth_os.pipeline.orchestrator import run_offline_pipeline


ROOT = Path(__file__).resolve().parents[1]
INPUT_DIGEST = parse_canonical_input_digest("1" * 64)


def _request(name: str):
    return decode_offline_run_request(
        parse_json_file(ROOT / "tests" / "fixtures" / name)
    )


def test_supported_request_reaches_approval_in_memory_without_filesystem_writes(
    tmp_path: Path,
) -> None:
    before = tuple(tmp_path.iterdir())

    result = run_offline_pipeline(
        ROOT,
        _request("topic_supported.json"),
        INPUT_DIGEST,
    )

    assert isinstance(result, PipelineReady)
    assert result.state_history == (
        PipelineState.TOPIC_VALIDATED,
        PipelineState.EVIDENCE_READY,
        PipelineState.BRIEF_READY,
        PipelineState.DRAFT_READY,
        PipelineState.QUALITY_PASSED,
        PipelineState.READY_FOR_APPROVAL,
    )
    assert result.external_write_count == 0
    assert result.draft.quality_status.value == "pass"
    assert result.article_html.startswith("<!doctype html>")
    assert result.body_hash.startswith("sha256:")
    assert result.metadata.get("state") is not None
    assert tuple(tmp_path.iterdir()) == before


def test_unsupported_factual_claim_blocks_before_rendering() -> None:
    result = run_offline_pipeline(
        ROOT,
        _request("topic_unsupported_claim.json"),
        INPUT_DIGEST,
    )

    assert isinstance(result, PipelineBlocked)
    assert result.state_history == (
        PipelineState.TOPIC_VALIDATED,
        PipelineState.EVIDENCE_READY,
        PipelineState.BRIEF_READY,
        PipelineState.DRAFT_READY,
        PipelineState.BLOCKED,
    )
    assert result.external_write_count == 0
    assert result.quality_report.status.value == "blocked"
    assert result.draft.quality_status.value == "blocked"
    assert result.reason_codes == ("CLAIM_EVIDENCE_REQUIRED",)


def test_unverified_first_person_experience_blocks_with_owner_evidence_reason() -> None:
    result = run_offline_pipeline(
        ROOT,
        _request("topic_unverified_experience.json"),
        INPUT_DIGEST,
    )

    assert isinstance(result, PipelineBlocked)
    assert result.reason_codes == ("OWNER_EVIDENCE_REQUIRED",)
    assert result.state_history[-1] is PipelineState.BLOCKED
    assert result.external_write_count == 0
