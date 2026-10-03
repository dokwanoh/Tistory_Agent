from __future__ import annotations

from tistory_growth_os.domain.content import ContentBrief, OfflineRunRequest
from tistory_growth_os.domain.ids import BriefId

from .evidence import (
    CanonicalInputDigest,
    build_evidence_pack,
    derive_identity,
    validate_request_references,
)


def build_content_brief(
    request: OfflineRunRequest,
    input_digest: CanonicalInputDigest,
) -> ContentBrief:
    validate_request_references(request)
    evidence = build_evidence_pack(request, input_digest)
    return ContentBrief(
        brief_id=BriefId(f"brief_{derive_identity('content-brief', input_digest)}"),
        topic_id=request.topic.topic_id,
        title=request.topic.title,
        target_audience=request.topic.target_audience,
        search_intent=request.topic.search_intent,
        core_question=request.topic.core_question,
        claim_ids=tuple(claim.claim_id for claim in request.claims),
        source_evidence_ids=tuple(item.source_id for item in evidence),
        section_ids=tuple(item.section_id for item in request.outline),
        as_of=request.topic.as_of,
    )
