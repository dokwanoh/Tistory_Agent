from __future__ import annotations

from pathlib import PurePosixPath

from tistory_growth_os.contracts.json_ast import (
    JsonValue,
)

from .common import (
    Fields,
    array,
    datetime_value,
    enum_value,
    fail,
    identifier,
    literal,
    strings,
    text,
)
from .publishing_future_decode import (
    decode_evolution_proposal as decode_evolution_proposal,
    decode_experiment as decode_experiment,
    decode_post_metrics as decode_post_metrics,
)
from .ids import (
    DraftId,
    IdempotencyKey,
    ManifestId,
    OwnerDecisionId,
    PackageId,
    QualityReportId,
)
from .publishing_decode_support import integer, number, require_version, require_zero
from .publishing import (
    ArtifactDescriptor,
    FindingCode,
    FindingSeverity,
    PublishManifest,
    QualityFinding,
    QualityReport,
    ReportStatus,
)


def decode_quality_report(value: JsonValue) -> QualityReport:
    fields = Fields.parse(value, "", (
        "schema_version", "report_id", "draft_id", "status", "score",
        "findings", "claim_evidence_coverage", "external_write_count", "evaluated_at",
    ))
    require_version(fields)
    require_zero(fields, "external_write_count")
    score = number(fields, "score")
    coverage = number(fields, "claim_evidence_coverage")
    if score > 100 or coverage > 1:
        pointer = "/score" if score > 100 else "/claim_evidence_coverage"
        fail(pointer, "maximum", "value exceeds contract maximum")
    findings = tuple(
        _decode_finding(item, f"/findings/{index}")
        for index, item in enumerate(array(fields, "findings", False))
    )
    return QualityReport(
        QualityReportId(identifier(fields, "report_id", r"quality_[a-f0-9]{16,64}")),
        DraftId(identifier(fields, "draft_id", r"draft_[a-f0-9]{16,64}")),
        enum_value(fields, "status", ReportStatus), score, findings, coverage,
        datetime_value(fields, "evaluated_at"),
    )


def decode_publish_manifest(value: JsonValue) -> PublishManifest:
    fields = Fields.parse(value, "", (
        "schema_version", "manifest_id", "package_id", "draft_id",
        "idempotency_key", "body_hash", "policy_snapshot_digest", "publish_mode",
        "state", "external_write_count", "artifacts", "pending_owner_decision_ids",
        "created_at",
    ))
    require_version(fields)
    _ = literal(fields, "publish_mode", "approval_required")
    _ = literal(fields, "state", "ready_for_approval")
    require_zero(fields, "external_write_count")
    body_hash = identifier(fields, "body_hash", r"sha256:[a-f0-9]{64}")
    policy_digest = identifier(fields, "policy_snapshot_digest", r"sha256:[a-f0-9]{64}")
    artifacts = tuple(
        _decode_artifact(item, f"/artifacts/{index}")
        for index, item in enumerate(array(fields, "artifacts", True))
    )
    decisions = tuple(
        OwnerDecisionId(item)
        for item in strings(fields, "pending_owner_decision_ids", False, r"ODR-[0-9]{3}")
    )
    paths = tuple(artifact.relative_path for artifact in artifacts)
    if len(paths) != len(set(paths)):
        fail("/artifacts", "uniqueItems", "artifact paths must be unique")
    return PublishManifest(
        ManifestId(identifier(fields, "manifest_id", r"manifest_[a-f0-9]{16,64}")),
        PackageId(identifier(fields, "package_id", r"package_[a-f0-9]{16,64}")),
        DraftId(identifier(fields, "draft_id", r"draft_[a-f0-9]{16,64}")),
        IdempotencyKey(text(fields, "idempotency_key")), body_hash, policy_digest,
        artifacts, decisions, datetime_value(fields, "created_at"),
    )


def _decode_finding(value: JsonValue, pointer: str) -> QualityFinding:
    fields = Fields.parse(value, pointer, ("code", "severity", "path", "message"))
    return QualityFinding(
        enum_value(fields, "code", FindingCode), enum_value(fields, "severity", FindingSeverity),
        text(fields, "path"), text(fields, "message"),
    )


def _decode_artifact(value: JsonValue, pointer: str) -> ArtifactDescriptor:
    fields = Fields.parse(
        value,
        pointer,
        (
            "name",
            "relative_path",
            "media_type",
            "byte_count",
            "sha256",
            "schema_version",
        ),
    )
    relative_path = text(fields, "relative_path")
    package_path = PurePosixPath(relative_path)
    if package_path.is_absolute() or ".." in package_path.parts:
        fail(fields.child("relative_path"), "path", "artifact path must stay inside the package")
    return ArtifactDescriptor(
        text(fields, "name"), relative_path, text(fields, "media_type"),
        integer(fields, "byte_count"), identifier(fields, "sha256", r"[a-f0-9]{64}"),
        literal(fields, "schema_version", "1.0.0"),
    )
