from __future__ import annotations

from urllib.parse import urlsplit

from tistory_growth_os.contracts.json_ast import JsonValue

from .common import (
    ClaimKind,
    DisclosureBasis,
    Fields,
    LicenseStatus,
    MediaKind,
    MediaLicenseStatus,
    OwnerEvidenceStatus,
    Provenance,
    SearchIntent,
    SourceType,
    SupportState,
    array,
    boolean,
    date_value,
    datetime_value,
    enum_value,
    fail,
    identifier,
    literal,
    strings,
    text,
)
from .content import (
    Claim,
    Disclosure,
    MediaPlaceholder,
    OfflineRunRequest,
    OfflineTopicInput,
    OutlineItem,
    SourceEvidence,
)
from .ids import (
    ClaimId,
    IdempotencyKey,
    MediaId,
    OwnerDecisionId,
    RequestId,
    SectionId,
    SourceId,
    TopicId,
)


def decode_offline_run_request(value: JsonValue) -> OfflineRunRequest:
    fields = Fields.parse(value, "", _REQUEST_KEYS)
    _version(fields)
    topic = OfflineTopicInput(
        topic_id=TopicId(identifier(fields, "topic_id", r"topic_[a-z0-9_-]{3,64}")),
        title=text(fields, "title"),
        topic_cluster=text(fields, "topic_cluster"),
        search_intent=enum_value(fields, "search_intent", SearchIntent),
        target_audience=text(fields, "target_audience"),
        core_question=text(fields, "core_question"),
        primary_language=literal(fields, "primary_language", "ko-KR"),
        as_of=date_value(fields, "as_of"),
    )
    outline = tuple(
        _decode_outline(item, f"/outline/{index}")
        for index, item in enumerate(array(fields, "outline", True))
    )
    evidence = tuple(
        decode_source_evidence_value(item, f"/source_evidence/{index}")
        for index, item in enumerate(array(fields, "source_evidence", True))
    )
    claims = tuple(
        decode_claim_value(item, f"/claims/{index}")
        for index, item in enumerate(array(fields, "claims", True))
    )
    media = tuple(
        _decode_media(item, f"/media/{index}")
        for index, item in enumerate(array(fields, "media", False))
    )
    disclosure = _decode_disclosure(fields.required("disclosure"), "/disclosure")
    decisions = tuple(
        OwnerDecisionId(item)
        for item in strings(fields, "owner_decision_ids", True, r"ODR-[0-9]{3}")
    )
    _validate_references(outline, evidence, claims)
    return OfflineRunRequest(
        request_id=RequestId(
            identifier(fields, "request_id", r"request_[a-z0-9_-]{3,64}")
        ),
        topic=topic,
        idempotency_key=IdempotencyKey(text(fields, "idempotency_key")),
        outline=outline,
        evidence=evidence,
        claims=claims,
        media=media,
        disclosure=disclosure,
        owner_decision_ids=decisions,
    )


def decode_source_evidence_value(value: JsonValue, pointer: str) -> SourceEvidence:
    fields = Fields.parse(value, pointer, _EVIDENCE_KEYS)
    _version(fields)
    url = text(fields, "url")
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        fail(fields.child("url"), "format", "expected absolute HTTP(S) URI")
    return SourceEvidence(
        source_id=SourceId(identifier(fields, "source_id", r"src_[a-z0-9_-]{3,64}")),
        source_type=enum_value(fields, "source_type", SourceType),
        url=url,
        title=text(fields, "title"),
        publisher=text(fields, "publisher"),
        provenance=Provenance(
            checked_at=datetime_value(fields, "checked_at"),
            as_of=date_value(fields, "as_of"),
        ),
        excerpt=text(fields, "excerpt"),
        license_status=enum_value(fields, "license_status", LicenseStatus),
        supports_claim_ids=tuple(
            ClaimId(item)
            for item in strings(
                fields,
                "supports_claim_ids",
                True,
                r"claim_[a-z0-9_-]{3,64}",
            )
        ),
    )


def decode_claim_value(value: JsonValue, pointer: str) -> Claim:
    fields = Fields.parse(value, pointer, _CLAIM_KEYS)
    _version(fields)
    return Claim(
        claim_id=ClaimId(identifier(fields, "claim_id", r"claim_[a-z0-9_-]{3,64}")),
        kind=enum_value(fields, "kind", ClaimKind),
        text=text(fields, "text"),
        support_state=enum_value(fields, "support_state", SupportState),
        evidence_ids=tuple(
            SourceId(item)
            for item in strings(fields, "evidence_ids", False, r"src_[a-z0-9_-]{3,64}")
        ),
        owner_evidence_status=enum_value(
            fields, "owner_evidence_status", OwnerEvidenceStatus
        ),
        as_of=date_value(fields, "as_of"),
    )


def _decode_outline(value: JsonValue, pointer: str) -> OutlineItem:
    fields = Fields.parse(
        value, pointer, ("section_id", "heading", "summary", "claim_ids")
    )
    return OutlineItem(
        section_id=SectionId(
            identifier(fields, "section_id", r"section_[a-z0-9_-]{3,64}")
        ),
        heading=text(fields, "heading"),
        summary=text(fields, "summary"),
        claim_ids=tuple(
            ClaimId(item)
            for item in strings(fields, "claim_ids", False, r"claim_[a-z0-9_-]{3,64}")
        ),
    )


def _decode_media(value: JsonValue, pointer: str) -> MediaPlaceholder:
    keys = ("media_id", "kind", "label", "alt", "license_status")
    fields = Fields.parse(value, pointer, keys)
    return MediaPlaceholder(
        media_id=MediaId(
            identifier(fields, "media_id", r"media_[a-z0-9_-]{3,64}")
        ),
        kind=enum_value(fields, "kind", MediaKind),
        label=text(fields, "label"),
        alt=text(fields, "alt"),
        license_status=enum_value(
            fields, "license_status", MediaLicenseStatus
        ),
    )


def _decode_disclosure(value: JsonValue, pointer: str) -> Disclosure:
    fields = Fields.parse(value, pointer, ("required", "text", "basis"))
    return Disclosure(
        required=boolean(fields, "required"),
        text=text(fields, "text"),
        basis=enum_value(fields, "basis", DisclosureBasis),
    )


def _validate_references(
    outline: tuple[OutlineItem, ...],
    evidence: tuple[SourceEvidence, ...],
    claims: tuple[Claim, ...],
) -> None:
    claim_ids = tuple(item.claim_id for item in claims)
    source_ids = tuple(item.source_id for item in evidence)
    if len(claim_ids) != len(set(claim_ids)):
        fail("/claims", "uniqueItems", "claim_id values must be unique")
    if len(source_ids) != len(set(source_ids)):
        fail("/source_evidence", "uniqueItems", "source_id values must be unique")
    for outline_index, item in enumerate(outline):
        for claim_index, claim_id in enumerate(item.claim_ids):
            if claim_id not in claim_ids:
                pointer = f"/outline/{outline_index}/claim_ids/{claim_index}"
                fail(pointer, "reference", "unknown claim_id")
    for evidence_index, item in enumerate(evidence):
        for claim_index, claim_id in enumerate(item.supports_claim_ids):
            if claim_id not in claim_ids:
                pointer = f"/source_evidence/{evidence_index}/supports_claim_ids/{claim_index}"
                fail(pointer, "reference", "unknown claim_id")
    for claim_index, item in enumerate(claims):
        for evidence_index, source_id in enumerate(item.evidence_ids):
            if source_id not in source_ids:
                pointer = f"/claims/{claim_index}/evidence_ids/{evidence_index}"
                fail(pointer, "reference", "unknown source_id")


def _version(fields: Fields) -> None:
    _ = literal(fields, "schema_version", "1.0.0")


_REQUEST_KEYS = (
    "schema_version", "request_id", "topic_id", "title", "topic_cluster",
    "search_intent", "target_audience", "core_question", "primary_language",
    "as_of", "idempotency_key", "outline", "source_evidence", "claims",
    "media", "disclosure", "owner_decision_ids",
)
_EVIDENCE_KEYS = (
    "schema_version", "source_id", "source_type", "url", "title", "publisher",
    "checked_at", "as_of", "excerpt", "license_status", "supports_claim_ids",
)
_CLAIM_KEYS = (
    "schema_version", "claim_id", "kind", "text", "support_state",
    "evidence_ids", "owner_evidence_status", "as_of",
)
