from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, unique
from pathlib import PurePosixPath
import re

from .ids import (
    DraftId,
    IdempotencyKey,
    ManifestId,
    OwnerDecisionId,
    PackageId,
    QualityReportId,
)
from .publishing_errors import PublishingInvariantError
from .publishing_future import (
    MetricSource as MetricSource,
    MetricStatus as MetricStatus,
    MetricValue as MetricValue,
    PostMetrics as PostMetrics,
    PublishedPost as PublishedPost,
    PublicState as PublicState,
    VerificationStatus as VerificationStatus,
)


@unique
class FindingCode(StrEnum):
    CLAIM_EVIDENCE_REQUIRED = "CLAIM_EVIDENCE_REQUIRED"
    OWNER_EVIDENCE_REQUIRED = "OWNER_EVIDENCE_REQUIRED"
    CONTRACT_INVALID = "CONTRACT_INVALID"
    POLICY_EVIDENCE_REQUIRED = "POLICY_EVIDENCE_REQUIRED"
    DISCLOSURE_REQUIRED = "DISCLOSURE_REQUIRED"
    PROHIBITED_AD_FORMAT = "PROHIBITED_AD_FORMAT"
    ACCESSIBILITY_REQUIRED = "ACCESSIBILITY_REQUIRED"


@unique
class FindingSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@unique
class ReportStatus(StrEnum):
    PASS = "pass"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class QualityFinding:
    code: FindingCode
    severity: FindingSeverity
    path: str
    message: str

    def __post_init__(self) -> None:
        if not self.path or not self.message:
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/findings",
                "finding path and message are required",
            )


@dataclass(frozen=True, slots=True)
class QualityReport:
    report_id: QualityReportId
    draft_id: DraftId
    status: ReportStatus
    score: Decimal
    findings: tuple[QualityFinding, ...]
    claim_evidence_coverage: Decimal
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if self.score < 0 or self.score > 100:
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/score",
                "quality score must be between 0 and 100",
            )
        if self.claim_evidence_coverage < 0 or self.claim_evidence_coverage > 1:
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/claim_evidence_coverage",
                "coverage must be between 0 and 1",
            )

    @property
    def external_write_count(self) -> int:
        return 0


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    name: str
    relative_path: str
    media_type: str
    byte_count: int
    sha256: str
    schema_version: str

    def __post_init__(self) -> None:
        if not self.name or not self.media_type:
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/artifacts",
                "name and media type are required",
            )
        path = PurePosixPath(self.relative_path)
        if not self.relative_path or path.is_absolute() or ".." in path.parts:
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/artifacts/relative_path",
                "path must stay inside the package",
            )
        if self.byte_count < 0:
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/artifacts/byte_count",
                "byte count cannot be negative",
            )
        if re.fullmatch(r"[a-f0-9]{64}", self.sha256) is None:
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/artifacts/sha256",
                "expected a SHA-256 hex digest",
            )
        if self.schema_version != "1.0.0":
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/artifacts/schema_version",
                "unsupported artifact schema version",
            )


@unique
class PublishMode(StrEnum):
    APPROVAL_REQUIRED = "approval_required"


@unique
class ApprovalState(StrEnum):
    READY_FOR_APPROVAL = "ready_for_approval"


@dataclass(frozen=True, slots=True)
class PublishManifest:
    manifest_id: ManifestId
    package_id: PackageId
    draft_id: DraftId
    idempotency_key: IdempotencyKey
    body_hash: str
    policy_snapshot_digest: str
    artifacts: tuple[ArtifactDescriptor, ...]
    pending_owner_decision_ids: tuple[OwnerDecisionId, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.artifacts:
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/artifacts",
                "at least one artifact is required",
            )
        digests = (
            ("/body_hash", self.body_hash),
            ("/policy_snapshot_digest", self.policy_snapshot_digest),
        )
        for path, value in digests:
            if re.fullmatch(r"sha256:[a-f0-9]{64}", value) is None:
                raise PublishingInvariantError(
                    "CONTRACT_INVALID",
                    path,
                    "expected a prefixed SHA-256 digest",
                )
        paths = tuple(artifact.relative_path for artifact in self.artifacts)
        if len(paths) != len(set(paths)):
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/artifacts",
                "artifact paths must be unique",
            )
        if len(self.pending_owner_decision_ids) != len(set(self.pending_owner_decision_ids)):
            raise PublishingInvariantError(
                "CONTRACT_INVALID",
                "/pending_owner_decision_ids",
                "owner decisions must be unique",
            )

    @property
    def publish_mode(self) -> PublishMode:
        return PublishMode.APPROVAL_REQUIRED

    @property
    def state(self) -> ApprovalState:
        return ApprovalState.READY_FOR_APPROVAL

    @property
    def external_write_count(self) -> int:
        return 0
