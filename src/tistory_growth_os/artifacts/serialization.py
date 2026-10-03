from __future__ import annotations

from ..contracts.json_ast import (
    JsonArray,
    JsonMember,
    JsonNumber,
    JsonObject,
    JsonString,
)
from ..domain.content import (
    ArticleDraft,
    ContentBrief,
    SourceEvidence,
)
from ..domain.publishing import (
    ArtifactDescriptor,
    PublishManifest,
    QualityFinding,
    QualityReport,
)
from ..domain.results import RunReport


def evidence_pack_json(evidence: tuple[SourceEvidence, ...]) -> JsonObject:
    return JsonObject((
        _string("schema_version", "1.0.0"),
        JsonMember(
            "source_evidence",
            JsonArray(tuple(source_evidence_json(item) for item in evidence)),
        ),
    ))


def source_evidence_json(value: SourceEvidence) -> JsonObject:
    return JsonObject((
        _string("schema_version", "1.0.0"),
        _string("source_id", value.source_id),
        _string("source_type", value.source_type.value),
        _string("url", value.url),
        _string("title", value.title),
        _string("publisher", value.publisher),
        _string("checked_at", value.checked_at.isoformat()),
        _string("as_of", value.as_of.isoformat()),
        _string("excerpt", value.excerpt),
        _string("license_status", value.license_status.value),
        _strings("supports_claim_ids", value.supports_claim_ids),
    ))


def content_brief_json(value: ContentBrief) -> JsonObject:
    return JsonObject((
        _string("schema_version", "1.0.0"),
        _string("brief_id", value.brief_id),
        _string("topic_id", value.topic_id),
        _string("title", value.title),
        _string("target_audience", value.target_audience),
        _string("search_intent", value.search_intent.value),
        _string("core_question", value.core_question),
        _strings("claim_ids", value.claim_ids),
        _strings("source_evidence_ids", value.source_evidence_ids),
        _strings("section_ids", value.section_ids),
        _string("as_of", value.as_of.isoformat()),
    ))


def article_draft_json(value: ArticleDraft) -> JsonObject:
    sections = tuple(
        JsonObject((
            _string("section_id", item.section_id),
            _string("heading", item.heading),
            _string("body", item.body),
            _strings("claim_ids", item.claim_ids),
            _strings("source_evidence_ids", item.source_evidence_ids),
        ))
        for item in value.sections
    )
    return JsonObject((
        _string("schema_version", "1.0.0"),
        _string("draft_id", value.draft_id),
        _string("brief_id", value.brief_id),
        _string("version", value.version),
        _string("title", value.title),
        _string("summary", value.summary),
        JsonMember("sections", JsonArray(sections)),
        _string("quality_status", value.quality_status.value),
        _string("as_of", value.as_of.isoformat()),
    ))


def quality_report_json(value: QualityReport) -> JsonObject:
    return JsonObject((
        _string("schema_version", "1.0.0"),
        _string("report_id", value.report_id),
        _string("draft_id", value.draft_id),
        _string("status", value.status.value),
        JsonMember("score", JsonNumber(value.score)),
        JsonMember(
            "findings",
            JsonArray(tuple(_quality_finding_json(item) for item in value.findings)),
        ),
        JsonMember(
            "claim_evidence_coverage",
            JsonNumber(value.claim_evidence_coverage),
        ),
        JsonMember("external_write_count", JsonNumber(0)),
        _string("evaluated_at", value.evaluated_at.isoformat()),
    ))


def publish_manifest_json(value: PublishManifest) -> JsonObject:
    return JsonObject((
        _string("schema_version", "1.0.0"),
        _string("manifest_id", value.manifest_id),
        _string("package_id", value.package_id),
        _string("draft_id", value.draft_id),
        _string("idempotency_key", value.idempotency_key),
        _string("body_hash", value.body_hash),
        _string("policy_snapshot_digest", value.policy_snapshot_digest),
        _string("publish_mode", value.publish_mode.value),
        _string("state", value.state.value),
        JsonMember("external_write_count", JsonNumber(0)),
        JsonMember(
            "artifacts",
            JsonArray(tuple(_artifact_json(item) for item in value.artifacts)),
        ),
        _strings("pending_owner_decision_ids", value.pending_owner_decision_ids),
        _string("created_at", value.created_at.isoformat()),
    ))


def run_report_json(value: RunReport) -> JsonObject:
    return JsonObject((
        _string("schema_version", "1.0.0"),
        _string("run_id", value.run_id),
        _string("request_id", value.request_id),
        _string("status", value.status.value),
        _string("result_code", value.result_code.value),
        _strings("state_history", value.state_history),
        _strings("artifact_paths", value.artifact_paths),
        JsonMember("external_write_count", JsonNumber(0)),
        _string("completed_at", value.completed_at.isoformat()),
    ))


def _quality_finding_json(value: QualityFinding) -> JsonObject:
    return JsonObject((
        _string("code", value.code.value),
        _string("severity", value.severity.value),
        _string("path", value.path),
        _string("message", value.message),
    ))


def _artifact_json(value: ArtifactDescriptor) -> JsonObject:
    return JsonObject((
        _string("name", value.name),
        _string("relative_path", value.relative_path),
        _string("media_type", value.media_type),
        JsonMember("byte_count", JsonNumber(value.byte_count)),
        _string("sha256", value.sha256),
        _string("schema_version", value.schema_version),
    ))


def _strings(key: str, values: tuple[str, ...]) -> JsonMember:
    return JsonMember(key, JsonArray(tuple(JsonString(item) for item in values)))


def _string(key: str, value: str) -> JsonMember:
    return JsonMember(key, JsonString(value))
