from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from tistory_growth_os.contracts.json_decode import JsonDecodeError, parse_json_file
from tistory_growth_os.domain.common import DisclosureBasis, QualityStatus
from tistory_growth_os.domain.content import Disclosure
from tistory_growth_os.domain.content_decode import decode_offline_run_request
from tistory_growth_os.domain.ids import ClaimId, SourceId
from tistory_growth_os.pipeline.brief import build_content_brief
from tistory_growth_os.pipeline.draft import build_article_draft
from tistory_growth_os.pipeline.evidence import (
    PIPELINE_VERSION,
    build_evidence_pack,
    parse_canonical_input_digest,
)


ROOT = Path(__file__).resolve().parents[1]
INPUT_DIGEST = "1" * 64


def _request():
    return decode_offline_run_request(
        parse_json_file(ROOT / "tests/fixtures/topic_supported.json")
    )


def _digest():
    return parse_canonical_input_digest(INPUT_DIGEST)


def _expected_identity(type_tag: str) -> str:
    material = f"{type_tag}\x00{INPUT_DIGEST}\x00{PIPELINE_VERSION}".encode("ascii")
    return sha256(material).hexdigest()


def test_supported_request_builds_stable_korean_evidence_brief_and_draft() -> None:
    # Given: a decoded, local-only Korean fixture and a caller-injected canonical digest.
    request = _request()
    digest = _digest()

    # When: the deterministic transformations run twice.
    evidence = build_evidence_pack(request, digest)
    brief = build_content_brief(request, digest)
    draft = build_article_draft(request, brief, digest)
    repeated = build_article_draft(request, build_content_brief(request, digest), digest)

    # Then: every value is stable, Korean text survives, and provenance is complete.
    assert evidence == build_evidence_pack(request, digest)
    assert brief == build_content_brief(request, digest)
    assert draft == repeated
    assert brief.brief_id == f"brief_{_expected_identity('content-brief')}"
    assert draft.draft_id == f"draft_{_expected_identity('article-draft')}"
    assert draft.version == PIPELINE_VERSION
    assert draft.quality_status is QualityStatus.NOT_EVALUATED
    assert draft.title == "티스토리 글 발행 전 품질 체크리스트"
    assert draft.summary == request.topic.core_question
    assert tuple(item.source_id for item in evidence) == tuple(
        sorted(item.source_id for item in request.evidence)
    )
    assert tuple(section.section_id for section in draft.sections) == tuple(
        item.section_id for item in request.outline
    )
    assert "현재 지원 경로와 정책을 확인한다" == draft.sections[0].heading
    assert "폐기된 API에 의존하지 않고" in draft.sections[0].body
    assert all(section.source_evidence_ids for section in draft.sections[:2])


def test_draft_uses_only_outlined_exact_claims_and_keeps_input_immutable() -> None:
    # Given: evidence deliberately ordered unlike the output order.
    request = _request()
    reversed_request = replace(request, evidence=tuple(reversed(request.evidence)))
    digest = _digest()
    original_evidence = reversed_request.evidence

    # When: a brief and draft are derived from the request.
    draft = build_article_draft(
        reversed_request,
        build_content_brief(reversed_request, digest),
        digest,
    )

    # Then: only exact outline claim text appears and the caller value is unchanged.
    body = "\n".join(section.body for section in draft.sections)
    for claim in reversed_request.claims:
        assert claim.text in body
    assert body.count(reversed_request.claims[0].text) == 1
    assert body.count(reversed_request.claims[1].text) == 1
    assert reversed_request.evidence == original_evidence
    assert tuple(item.source_id for item in build_evidence_pack(reversed_request, digest)) == tuple(
        sorted(item.source_id for item in original_evidence)
    )


def test_dangling_reference_in_outline_claim_fails_closed_at_exact_path() -> None:
    # Given: a direct typed construction that bypasses the boundary decoder.
    request = _request()
    outline = (
        replace(request.outline[0], claim_ids=(ClaimId("claim_missing"),)),
        *request.outline[1:],
    )
    invalid_request = replace(request, outline=outline)

    # When: draft construction rechecks cross references defensively.
    with pytest.raises(JsonDecodeError) as caught:
        _ = build_article_draft(
            invalid_request,
            build_content_brief(invalid_request, _digest()),
            _digest(),
        )

    # Then: no draft is returned and the broken field has a stable contract path.
    assert caught.value.issue.code == "CONTRACT_INVALID"
    assert caught.value.issue.pointer == "/outline/0/claim_ids/0"


def test_bidirectional_claim_source_mismatch_fails_closed_at_exact_path() -> None:
    # Given: a claim names a known source that does not claim it in reverse.
    request = _request()
    first_claim = replace(
        request.claims[0],
        evidence_ids=(SourceId("src_google_gen_ai"),),
    )
    invalid_request = replace(request, claims=(first_claim, *request.claims[1:]))

    # When: transformation validates its typed input again at the seam.
    with pytest.raises(JsonDecodeError) as caught:
        _ = build_evidence_pack(invalid_request, _digest())

    # Then: bidirectional provenance is required before an evidence pack exists.
    assert caught.value.issue.code == "CONTRACT_INVALID"
    assert caught.value.issue.pointer == "/claims/0/evidence_ids/0"


def test_required_disclosure_is_present_only_in_draft_opening_summary() -> None:
    # Given: otherwise equal requests with and without an explicit disclosure requirement.
    request = _request()
    required = replace(
        request,
        disclosure=Disclosure(True, "광고성 정보와 제휴 관계를 고지합니다.", DisclosureBasis.AFFILIATE),
    )
    digest = _digest()

    # When: drafts are derived from both typed requests.
    disclosed = build_article_draft(required, build_content_brief(required, digest), digest)
    undisclosed = build_article_draft(request, build_content_brief(request, digest), digest)

    # Then: the supplied disclosure appears only for the required variant.
    assert disclosed.summary.startswith(required.disclosure.text)
    assert request.disclosure.text not in undisclosed.summary


def test_canonical_input_digest_requires_lowercase_sha256_hex() -> None:
    # Given: an invalid caller supplied digest.
    invalid_digest = "ABC"

    # When: the stable digest contract is parsed.
    with pytest.raises(JsonDecodeError) as caught:
        _ = parse_canonical_input_digest(invalid_digest)

    # Then: downstream identity generation cannot proceed with ambiguous material.
    assert caught.value.issue.code == "CONTRACT_INVALID"
    assert caught.value.issue.pointer == "/input_digest"
