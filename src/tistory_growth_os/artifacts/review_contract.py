from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import Final, NewType

from ..contracts.json_ast import JsonValue
from ..domain.common import Fields, datetime_value, enum_value, fail, identifier, literal


ReviewDigest = NewType("ReviewDigest", str)


@unique
class ReviewDecision(StrEnum):
    APPROVED = "approved"
    HOLD = "hold"
    REJECTED = "rejected"


@unique
class ReviewerKind(StrEnum):
    HUMAN = "human"
    INDEPENDENT_AGENT = "independent_agent"


@unique
class ReviewCode(StrEnum):
    APPROVED = "REVIEW_APPROVED"
    REQUIRED = "REVIEW_REQUIRED"
    INVALID = "REVIEW_INVALID"
    MISMATCH = "REVIEW_MISMATCH"
    HELD = "REVIEW_HELD"
    REJECTED = "REVIEW_REJECTED"
    EXPIRED = "REVIEW_EXPIRED"
    NOT_YET_VALID = "REVIEW_NOT_YET_VALID"
    EVIDENCE_NEWER = "REVIEW_EVIDENCE_NEWER"


@dataclass(frozen=True, slots=True)
class ReviewSubject:
    digest: ReviewDigest
    evidence_checked_at: datetime


@dataclass(frozen=True, slots=True)
class PackageReview:
    review_id: str
    reviewer_id: str
    reviewer_kind: ReviewerKind
    decision: ReviewDecision
    subject_sha256: ReviewDigest
    reviewed_at: datetime
    valid_until: datetime
    evidence_valid_until: datetime
    policy_valid_until: datetime


@dataclass(frozen=True, slots=True)
class ReviewCheck:
    code: ReviewCode
    review_id: str = ""
    reviewer_kind: str = ""


_KEYS: Final = (
    "schema_version", "scope", "review_id", "reviewer_id", "reviewer_kind", "decision",
    "subject_sha256", "reviewed_at", "valid_until", "evidence_valid_until", "policy_valid_until",
)


def decode_package_review(value: JsonValue) -> PackageReview:
    fields = Fields.parse(value, "", _KEYS)
    _ = literal(fields, "schema_version", "1.0.0")
    _ = literal(fields, "scope", "local_package_only")
    record = PackageReview(
        identifier(fields, "review_id", r"review_[a-z0-9_-]{3,64}"),
        identifier(fields, "reviewer_id", r"[a-z0-9_-]{3,64}"),
        enum_value(fields, "reviewer_kind", ReviewerKind),
        enum_value(fields, "decision", ReviewDecision),
        ReviewDigest(identifier(fields, "subject_sha256", r"[a-f0-9]{64}")),
        datetime_value(fields, "reviewed_at"), datetime_value(fields, "valid_until"),
        datetime_value(fields, "evidence_valid_until"), datetime_value(fields, "policy_valid_until"),
    )
    if record.reviewed_at >= min(record.valid_until, record.evidence_valid_until, record.policy_valid_until):
        fail("/valid_until", "range", "every validity limit must follow reviewed_at")
    return record
