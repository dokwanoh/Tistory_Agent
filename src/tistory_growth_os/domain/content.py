from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .common import (
    ClaimKind,
    Confidence,
    DisclosureBasis,
    LicenseStatus,
    MediaKind,
    MediaLicenseStatus,
    OwnerEvidenceStatus,
    Provenance,
    QualityStatus,
    SearchIntent,
    SourceType,
    SupportState,
    TopicStatus,
    UnknownScore,
)
from .ids import (
    BriefId,
    ClaimId,
    DraftId,
    IdempotencyKey,
    MediaId,
    OpportunityId,
    OwnerDecisionId,
    RequestId,
    SectionId,
    SourceId,
    TopicId,
)


@dataclass(frozen=True, slots=True)
class TopicCandidate:
    topic_id: TopicId
    title: str
    topic_cluster: str
    search_intent: SearchIntent
    target_audience: str
    core_question: str
    primary_language: str
    as_of: date
    status: TopicStatus


@dataclass(frozen=True, slots=True)
class ContentOpportunity:
    opportunity_id: OpportunityId
    topic_id: TopicId
    demand_score: Decimal | UnknownScore
    authority_score: Decimal | UnknownScore
    reader_value_score: Decimal | UnknownScore
    monetization_score: Decimal | UnknownScore
    risk_penalty: Decimal | UnknownScore
    cannibalization_penalty: Decimal | UnknownScore
    confidence: Confidence
    score_version: str
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    source_id: SourceId
    source_type: SourceType
    url: str
    title: str
    publisher: str
    provenance: Provenance
    excerpt: str
    license_status: LicenseStatus
    supports_claim_ids: tuple[ClaimId, ...]

    @property
    def checked_at(self) -> datetime:
        return self.provenance.checked_at

    @property
    def as_of(self) -> date:
        return self.provenance.as_of


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: ClaimId
    kind: ClaimKind
    text: str
    support_state: SupportState
    evidence_ids: tuple[SourceId, ...]
    owner_evidence_status: OwnerEvidenceStatus
    as_of: date


@dataclass(frozen=True, slots=True)
class ContentBrief:
    brief_id: BriefId
    topic_id: TopicId
    title: str
    target_audience: str
    search_intent: SearchIntent
    core_question: str
    claim_ids: tuple[ClaimId, ...]
    source_evidence_ids: tuple[SourceId, ...]
    section_ids: tuple[SectionId, ...]
    as_of: date


@dataclass(frozen=True, slots=True)
class DraftSection:
    section_id: SectionId
    heading: str
    body: str
    claim_ids: tuple[ClaimId, ...]
    source_evidence_ids: tuple[SourceId, ...]


@dataclass(frozen=True, slots=True)
class ArticleDraft:
    draft_id: DraftId
    brief_id: BriefId
    version: str
    title: str
    summary: str
    sections: tuple[DraftSection, ...]
    quality_status: QualityStatus
    as_of: date


@dataclass(frozen=True, slots=True)
class OutlineItem:
    section_id: SectionId
    heading: str
    summary: str
    claim_ids: tuple[ClaimId, ...]


@dataclass(frozen=True, slots=True)
class MediaPlaceholder:
    media_id: MediaId
    kind: MediaKind
    label: str
    alt: str
    license_status: MediaLicenseStatus


@dataclass(frozen=True, slots=True)
class Disclosure:
    required: bool
    text: str
    basis: DisclosureBasis


@dataclass(frozen=True, slots=True)
class OfflineTopicInput:
    topic_id: TopicId
    title: str
    topic_cluster: str
    search_intent: SearchIntent
    target_audience: str
    core_question: str
    primary_language: str
    as_of: date


@dataclass(frozen=True, slots=True)
class OfflineRunRequest:
    request_id: RequestId
    topic: OfflineTopicInput
    idempotency_key: IdempotencyKey
    outline: tuple[OutlineItem, ...]
    evidence: tuple[SourceEvidence, ...]
    claims: tuple[Claim, ...]
    media: tuple[MediaPlaceholder, ...]
    disclosure: Disclosure
    owner_decision_ids: tuple[OwnerDecisionId, ...]
