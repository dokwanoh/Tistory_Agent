from __future__ import annotations

from tistory_growth_os.contracts.json_ast import JsonValue

from .common import (
    Confidence,
    Fields,
    QualityStatus,
    SearchIntent,
    TopicStatus,
    array,
    date_value,
    datetime_value,
    enum_value,
    identifier,
    literal,
    score,
    strings,
    text,
)
from .content import (
    ArticleDraft,
    Claim,
    ContentBrief,
    ContentOpportunity,
    DraftSection,
    SourceEvidence,
    TopicCandidate,
)
from .content_request_decode import (
    decode_claim_value,
    decode_offline_run_request as decode_offline_run_request,
    decode_source_evidence_value,
)
from .ids import BriefId, ClaimId, DraftId, OpportunityId, SectionId, SourceId, TopicId


def decode_content_opportunity(value: JsonValue) -> ContentOpportunity:
    keys = (
        "schema_version",
        "opportunity_id",
        "topic_id",
        "demand_score",
        "authority_score",
        "reader_value_score",
        "monetization_score",
        "risk_penalty",
        "cannibalization_penalty",
        "confidence",
        "score_version",
        "evaluated_at",
    )
    fields = Fields.parse(value, "", keys)
    _version(fields)
    return ContentOpportunity(
        opportunity_id=OpportunityId(
            identifier(fields, "opportunity_id", r"opp_[a-z0-9_-]{3,64}")
        ),
        topic_id=TopicId(
            identifier(fields, "topic_id", r"topic_[a-z0-9_-]{3,64}")
        ),
        demand_score=score(fields, "demand_score"),
        authority_score=score(fields, "authority_score"),
        reader_value_score=score(fields, "reader_value_score"),
        monetization_score=score(fields, "monetization_score"),
        risk_penalty=score(fields, "risk_penalty"),
        cannibalization_penalty=score(fields, "cannibalization_penalty"),
        confidence=enum_value(fields, "confidence", Confidence),
        score_version=text(fields, "score_version"),
        evaluated_at=datetime_value(fields, "evaluated_at"),
    )


def decode_topic_candidate(value: JsonValue) -> TopicCandidate:
    keys = (
        "schema_version",
        "topic_id",
        "title",
        "topic_cluster",
        "search_intent",
        "target_audience",
        "core_question",
        "primary_language",
        "as_of",
        "status",
    )
    fields = Fields.parse(value, "", keys)
    _version(fields)
    return TopicCandidate(
        topic_id=TopicId(
            identifier(fields, "topic_id", r"topic_[a-z0-9_-]{3,64}")
        ),
        title=text(fields, "title"),
        topic_cluster=text(fields, "topic_cluster"),
        search_intent=enum_value(fields, "search_intent", SearchIntent),
        target_audience=text(fields, "target_audience"),
        core_question=text(fields, "core_question"),
        primary_language=literal(fields, "primary_language", "ko-KR"),
        as_of=date_value(fields, "as_of"),
        status=enum_value(fields, "status", TopicStatus),
    )


def decode_source_evidence(value: JsonValue) -> SourceEvidence:
    return decode_source_evidence_value(value, "")


def decode_claim(value: JsonValue) -> Claim:
    return decode_claim_value(value, "")


def decode_content_brief(value: JsonValue) -> ContentBrief:
    keys = (
        "schema_version",
        "brief_id",
        "topic_id",
        "title",
        "target_audience",
        "search_intent",
        "core_question",
        "claim_ids",
        "source_evidence_ids",
        "section_ids",
        "as_of",
    )
    fields = Fields.parse(value, "", keys)
    _version(fields)
    return ContentBrief(
        brief_id=BriefId(
            identifier(fields, "brief_id", r"brief_[a-f0-9]{16,64}")
        ),
        topic_id=TopicId(
            identifier(fields, "topic_id", r"topic_[a-z0-9_-]{3,64}")
        ),
        title=text(fields, "title"),
        target_audience=text(fields, "target_audience"),
        search_intent=enum_value(fields, "search_intent", SearchIntent),
        core_question=text(fields, "core_question"),
        claim_ids=tuple(
            ClaimId(item)
            for item in strings(fields, "claim_ids", True, r"claim_[a-z0-9_-]{3,64}")
        ),
        source_evidence_ids=tuple(
            SourceId(item)
            for item in strings(
                fields,
                "source_evidence_ids",
                True,
                r"src_[a-z0-9_-]{3,64}",
            )
        ),
        section_ids=tuple(
            SectionId(item)
            for item in strings(
                fields,
                "section_ids",
                True,
                r"section_[a-z0-9_-]{3,64}",
            )
        ),
        as_of=date_value(fields, "as_of"),
    )


def decode_article_draft(value: JsonValue) -> ArticleDraft:
    keys = (
        "schema_version",
        "draft_id",
        "brief_id",
        "version",
        "title",
        "summary",
        "sections",
        "quality_status",
        "as_of",
    )
    fields = Fields.parse(value, "", keys)
    _version(fields)
    sections = tuple(
        _decode_draft_section(item, f"/sections/{index}")
        for index, item in enumerate(array(fields, "sections", True))
    )
    return ArticleDraft(
        draft_id=DraftId(
            identifier(fields, "draft_id", r"draft_[a-f0-9]{16,64}")
        ),
        brief_id=BriefId(
            identifier(fields, "brief_id", r"brief_[a-f0-9]{16,64}")
        ),
        version=identifier(fields, "version", r"[0-9]+\.[0-9]+\.[0-9]+"),
        title=text(fields, "title"),
        summary=text(fields, "summary"),
        sections=sections,
        quality_status=enum_value(fields, "quality_status", QualityStatus),
        as_of=date_value(fields, "as_of"),
    )


def _decode_draft_section(value: JsonValue, pointer: str) -> DraftSection:
    keys = (
        "section_id",
        "heading",
        "body",
        "claim_ids",
        "source_evidence_ids",
    )
    fields = Fields.parse(value, pointer, keys)
    return DraftSection(
        section_id=SectionId(
            identifier(fields, "section_id", r"section_[a-z0-9_-]{3,64}")
        ),
        heading=text(fields, "heading"),
        body=text(fields, "body"),
        claim_ids=tuple(
            ClaimId(item)
            for item in strings(fields, "claim_ids", False, r"claim_[a-z0-9_-]{3,64}")
        ),
        source_evidence_ids=tuple(
            SourceId(item)
            for item in strings(
                fields,
                "source_evidence_ids",
                False,
                r"src_[a-z0-9_-]{3,64}",
            )
        ),
    )


def _version(fields: Fields) -> None:
    _ = literal(fields, "schema_version", "1.0.0")
