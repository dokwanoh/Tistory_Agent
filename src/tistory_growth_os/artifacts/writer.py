from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from hashlib import sha256
import os
from pathlib import Path
import shutil
import tempfile
from typing import Final

from ..audit.events import audit_event_json, bundle_audit_json
from ..contracts.json_ast import JsonBoolean, JsonMember, JsonNumber, JsonObject, JsonString
from ..contracts.json_encode import encode_json_bytes
from ..contracts.registry import ContractRegistry
from ..domain.ids import ManifestId, PackageId
from ..domain.publishing import ArtifactDescriptor, PublishManifest
from ..domain.results import PipelineReady
from ..pipeline.evidence import PIPELINE_VERSION
from .layout import ArtifactWriteError, safe_output_root
from .package_review import enforce_package_review, payload_digest
from .package_validation import normalize_and_match_input, validate_existing_package
from .review_contract import ReviewSubject
from .serialization import (
    article_draft_json,
    content_brief_json,
    evidence_pack_json,
    publish_manifest_json,
    quality_report_json,
    source_evidence_json,
)


@unique
class BundleWriteStatus(StrEnum):
    CREATED = "created"
    IDEMPOTENT_REPLAY = "idempotent_replay"


@dataclass(frozen=True, slots=True)
class BundleWriteResult:
    status: BundleWriteStatus
    bundle_path: Path
    package_id: str
    manifest_id: str
    external_write_count: int = 0


_MEDIA_TYPES: Final[dict[str, str]] = {
    "article.html": "text/html; charset=utf-8",
    "evidence.json": "application/json",
    "content-brief.json": "application/json",
    "article-draft.json": "application/json",
    "quality-report.json": "application/json",
    "metadata.json": "application/json",
    "rollback.json": "application/json",
    "audit.json": "application/json",
    "checksums.json": "application/json",
}


def write_approval_bundle(
    project_root: Path,
    output_relative: str,
    ready: PipelineReady,
    canonical_input: bytes,
) -> BundleWriteResult:
    output = safe_output_root(project_root, output_relative)
    normalized = normalize_and_match_input(project_root, canonical_input, ready)
    schema_digest = _schema_catalog_digest(project_root)
    policy_digest = _policy_digest(project_root)
    package_id = _package_id(normalized, schema_digest, policy_digest)
    bundle = output / "bundle"
    if bundle.is_symlink():
        raise ArtifactWriteError(
            "OUTPUT_PATH_INVALID", "/output/bundle", "bundle symlink is forbidden"
        )
    payloads, manifest = _build_payloads(
        project_root,
        ready,
        package_id,
        policy_digest,
    )
    enforce_package_review(project_root, output, ReviewSubject(
        payload_digest(payloads), max(item.checked_at for item in ready.evidence),
    ))
    if bundle.exists():
        validate_existing_package(bundle, payloads, manifest)
        _append_event(output, "idempotent_replay", package_id, ready.request.request_id)
        return BundleWriteResult(
            BundleWriteStatus.IDEMPOTENT_REPLAY, bundle, package_id, manifest.manifest_id,
        )
    _write_atomic_bundle(output, bundle, payloads)
    _append_event(output, "bundle_created", package_id, ready.request.request_id)
    return BundleWriteResult(
        BundleWriteStatus.CREATED,
        bundle,
        package_id,
        manifest.manifest_id,
    )


def review_candidate_json(root: Path, ready: PipelineReady, canonical: bytes) -> JsonObject:
    normalized = normalize_and_match_input(root, canonical, ready)
    policy_digest = _policy_digest(root)
    package_id = _package_id(normalized, _schema_catalog_digest(root), policy_digest)
    payloads, _ = _build_payloads(root, ready, package_id, policy_digest)
    return JsonObject((
        JsonMember("schema_version", JsonString("1.0.0")),
        JsonMember("event", JsonString("review_candidate_prepared")),
        JsonMember("scope", JsonString("inspection_only")),
        JsonMember("status", JsonString("REVIEW_REQUIRED")),
        JsonMember("approval_eligible", JsonBoolean(False)),
        JsonMember("external_write_count", JsonNumber(0)),
        JsonMember("subject_sha256", JsonString(payload_digest(payloads))),
        JsonMember("evidence_checked_at", JsonString(max(item.checked_at for item in ready.evidence).isoformat())),
        JsonMember("candidate_files_utf8", JsonObject(tuple(
            JsonMember(name, JsonString(body.decode("utf-8")))
            for name, body in sorted(payloads.items())
        ))),
    ))


def _schema_catalog_digest(root: Path) -> str:
    registry = ContractRegistry.load(root / "contracts")
    digest = sha256()
    catalog = root / "contracts" / "catalog.json"
    digest.update(catalog.read_bytes())
    for entry in sorted(registry.entries, key=lambda item: item.file):
        digest.update(entry.file.encode("utf-8"))
        digest.update((root / "contracts" / entry.file).read_bytes())
    return digest.hexdigest()


def _policy_digest(root: Path) -> str:
    digest = sha256()
    for name in ("owner-decisions.json", "policy-evidence.json"):
        digest.update(name.encode("ascii"))
        digest.update((root / "contracts" / name).read_bytes())
    return digest.hexdigest()


def _package_id(canonical: bytes, schema_digest: str, policy_digest: str) -> str:
    digest = sha256()
    for part in (
        canonical,
        PIPELINE_VERSION.encode("ascii"),
        schema_digest.encode("ascii"),
        policy_digest.encode("ascii"),
    ):
        digest.update(part)
        digest.update(b"\x00")
    return f"package_{digest.hexdigest()}"


def _build_payloads(
    root: Path,
    ready: PipelineReady,
    package_id: str,
    policy_digest: str,
) -> tuple[dict[str, bytes], PublishManifest]:
    registry = ContractRegistry.load(root / "contracts")
    values = {
        "evidence.json": evidence_pack_json(ready.evidence),
        "content-brief.json": content_brief_json(ready.brief),
        "article-draft.json": article_draft_json(ready.draft),
        "quality-report.json": quality_report_json(ready.quality_report),
        "metadata.json": ready.metadata,
        "rollback.json": ready.rollback,
        "audit.json": bundle_audit_json(ready, package_id),
    }
    _validate_values(registry, ready)
    payloads = {name: encode_json_bytes(value) for name, value in values.items()}
    payloads["article.html"] = ready.article_html.encode("utf-8")
    payloads["checksums.json"] = encode_json_bytes(_checksums(payloads))
    descriptors = tuple(_descriptor(name, body) for name, body in sorted(payloads.items()))
    manifest_digest = sha256(f"{package_id}\x00manifest".encode("ascii")).hexdigest()
    manifest = PublishManifest(
        ManifestId(f"manifest_{manifest_digest}"),
        PackageId(package_id),
        ready.draft.draft_id,
        ready.request.idempotency_key,
        ready.body_hash,
        f"sha256:{policy_digest}",
        descriptors,
        ready.request.owner_decision_ids,
        ready.quality_report.evaluated_at,
    )
    manifest_value = publish_manifest_json(manifest)
    issues = registry.validate("publish-manifest", manifest_value)
    if issues:
        first = issues[0]
        raise ArtifactWriteError("ARTIFACT_SCHEMA_INVALID", first.pointer, first.message)
    payloads["publish-manifest.json"] = encode_json_bytes(manifest_value)
    return payloads, manifest


def _validate_values(registry: ContractRegistry, ready: PipelineReady) -> None:
    pairs = (
        ("content-brief", content_brief_json(ready.brief)),
        ("article-draft", article_draft_json(ready.draft)),
        ("quality-report", quality_report_json(ready.quality_report)),
    )
    for name, value in pairs:
        issues = registry.validate(name, value)
        if issues:
            first = issues[0]
            raise ArtifactWriteError("ARTIFACT_SCHEMA_INVALID", first.pointer, first.message)
    for source in ready.evidence:
        issues = registry.validate("source-evidence", source_evidence_json(source))
        if issues:
            first = issues[0]
            raise ArtifactWriteError("ARTIFACT_SCHEMA_INVALID", first.pointer, first.message)


def _checksums(payloads: dict[str, bytes]) -> JsonObject:
    members = tuple(
        JsonMember(name, JsonString(f"sha256:{sha256(body).hexdigest()}"))
        for name, body in sorted(payloads.items())
    )
    return JsonObject((JsonMember("algorithm", JsonString("sha256")), *members))


def _descriptor(name: str, body: bytes) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        name,
        name,
        _MEDIA_TYPES[name],
        len(body),
        sha256(body).hexdigest(),
        "1.0.0",
    )


def _write_atomic_bundle(
    output: Path,
    bundle: Path,
    payloads: dict[str, bytes],
) -> None:
    _ = output.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".bundle-staging-", dir=output))
    try:
        for name, body in payloads.items():
            _ = (staging / name).write_bytes(body)
        _ = os.replace(staging, bundle)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _append_event(output: Path, event: str, package_id: str, request_id: str) -> None:
    payload = encode_json_bytes(audit_event_json(event, package_id, request_id))
    with (output / "audit.jsonl").open("ab") as stream:
        _ = stream.write(payload)


__all__ = [
    "ArtifactWriteError",
    "BundleWriteResult",
    "BundleWriteStatus",
    "write_approval_bundle",
]
