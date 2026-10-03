from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum, unique
from typing import NewType


BlogUrl = NewType("BlogUrl", str)
CanonicalUrl = NewType("CanonicalUrl", str)


@unique
class IntentHint(StrEnum):
    EXPLANATION = "explanation"
    HOW_TO = "how_to"
    SCHEDULE = "schedule"
    COMPARISON = "comparison"


@unique
class FreshnessClass(StrEnum):
    REVIEW_REQUIRED = "review_required"
    TIME_SENSITIVE_STALE = "time_sensitive_stale"
    EVERGREEN_REVIEW_DUE = "evergreen_review_due"


@unique
class RiskClass(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@unique
class ActionCandidate(StrEnum):
    HIGH_RISK_REVIEW = "high_risk_review"
    REFRESH_OR_RETIRE = "refresh_or_retire"
    CLUSTER_REVIEW = "cluster_review"


@dataclass(frozen=True, slots=True)
class PublicPostSnapshot:
    canonical_url: CanonicalUrl
    title: str
    published_at: datetime
    modified_at: datetime
    category: str


@dataclass(frozen=True, slots=True)
class PublicInventoryRequest:
    blog_url: BlogUrl
    checked_date: date
    posts: tuple[PublicPostSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ClassifiedPost:
    snapshot: PublicPostSnapshot
    intent_hint: IntentHint
    freshness_class: FreshnessClass
    risk_class: RiskClass
    action_candidate: ActionCandidate
