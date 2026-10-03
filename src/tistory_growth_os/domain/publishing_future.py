from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum, unique

from .ids import ManifestId, MetricsId, PostId
from .publishing_errors import PublishingInvariantError


@unique
class PublicState(StrEnum):
    DRAFT = "draft"
    PRIVATE = "private"
    PUBLISHED = "published"


@unique
class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PublishedPost:
    post_id: PostId
    manifest_id: ManifestId
    actual_url: str
    title: str
    public_state: PublicState
    body_hash: str
    published_at: datetime
    verified_at: datetime
    verification_status: VerificationStatus


@unique
class MetricSource(StrEnum):
    TISTORY = "tistory"
    GOOGLE_SEARCH_CONSOLE = "google_search_console"
    NAVER_SEARCH_ADVISOR = "naver_search_advisor"
    ADSENSE = "adsense"
    OWNER = "owner"


@unique
class MetricStatus(StrEnum):
    UNKNOWN = "unknown"
    UNAUTHORIZED = "unauthorized"
    OBSERVED = "observed"


@dataclass(frozen=True, slots=True)
class MetricValue:
    metric: str
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        if not self.metric or not self.unit or self.value < 0:
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/values",
                "metric, unit, and non-negative value are required",
            )


@dataclass(frozen=True, slots=True)
class PostMetrics:
    metrics_id: MetricsId
    post_id: PostId
    source: MetricSource
    surface: str
    status: MetricStatus
    interval_start: date
    interval_end: date
    update_basis_date: date
    ingested_at: datetime
    retention_days: int
    is_truncated: bool
    values: tuple[MetricValue, ...]

    def __post_init__(self) -> None:
        invalid_provenance = (
            not self.surface
            or self.interval_end < self.interval_start
            or self.retention_days < 0
        )
        if invalid_provenance:
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/",
                "metric provenance or interval is invalid",
            )
        match self.status:
            case MetricStatus.UNKNOWN | MetricStatus.UNAUTHORIZED:
                if self.values:
                    raise PublishingInvariantError(
                        "CONTRACT_INVALID",
                        "/values",
                        "unobserved metrics cannot carry numeric values",
                    )
            case MetricStatus.OBSERVED:
                pass
