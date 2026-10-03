from __future__ import annotations

from tistory_growth_os.contracts.json_decode import ContractIssue, JsonDecodeError
from tistory_growth_os.domain.common import QualityStatus
from tistory_growth_os.domain.content import (
    ArticleDraft,
    ContentBrief,
    DraftSection,
    OfflineRunRequest,
    SourceEvidence,
)
from tistory_growth_os.domain.ids import ClaimId, DraftId, SourceId

from .brief import build_content_brief
from .evidence import CanonicalInputDigest, build_evidence_pack, derive_identity, validate_request_references


def build_article_draft(
    request: OfflineRunRequest,
    brief: ContentBrief,
    input_digest: CanonicalInputDigest,
) -> ArticleDraft:
    validate_request_references(request)
    _validate_brief(request, brief, input_digest)
    evidence = build_evidence_pack(request, input_digest)
    claim_texts: dict[ClaimId, str] = {
        item.claim_id: item.text for item in request.claims
    }
    sections = tuple(
        _draft_section(outline_index, request, claim_texts, evidence)
        for outline_index in range(len(request.outline))
    )
    return ArticleDraft(
        draft_id=DraftId(f"draft_{derive_identity('article-draft', input_digest)}"),
        brief_id=brief.brief_id,
        version="0.2.1",
        title=request.topic.title,
        summary=_opening_summary(request),
        sections=sections,
        quality_status=QualityStatus.NOT_EVALUATED,
        as_of=request.topic.as_of,
    )


def _validate_brief(
    request: OfflineRunRequest,
    brief: ContentBrief,
    input_digest: CanonicalInputDigest,
) -> None:
    if brief != build_content_brief(request, input_digest):
        raise JsonDecodeError(
            ContractIssue(
                pointer="/content_brief",
                keyword="const",
                message="brief does not match request and canonical input digest",
            )
        )


def _draft_section(
    outline_index: int,
    request: OfflineRunRequest,
    claim_texts: dict[ClaimId, str],
    evidence: tuple[SourceEvidence, ...],
) -> DraftSection:
    outline = request.outline[outline_index]
    claim_ids = outline.claim_ids
    claim_text = tuple(claim_texts[claim_id] for claim_id in claim_ids)
    source_ids = _section_source_ids(claim_ids, evidence)
    body = _section_body(outline.summary, claim_text)
    return DraftSection(
        section_id=outline.section_id,
        heading=outline.heading,
        body=body,
        claim_ids=claim_ids,
        source_evidence_ids=source_ids,
    )


def _section_body(summary: str, claim_text: tuple[str, ...]) -> str:
    if not claim_text:
        return summary
    return f"{summary}\n\n" + "\n\n".join(claim_text)


def _section_source_ids(
    claim_ids: tuple[ClaimId, ...],
    evidence: tuple[SourceEvidence, ...],
) -> tuple[SourceId, ...]:
    return tuple(
        item.source_id
        for item in evidence
        if any(claim_id in item.supports_claim_ids for claim_id in claim_ids)
    )


def _opening_summary(request: OfflineRunRequest) -> str:
    if request.disclosure.required:
        return f"{request.disclosure.text}\n\n{request.topic.core_question}"
    return request.topic.core_question
