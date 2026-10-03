from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

from ..contracts.json_decode import JsonDecodeError, parse_json
from ..contracts.json_encode import encode_json_bytes
from ..domain.content_request_decode import decode_offline_run_request
from ..domain.publishing import PublishManifest
from ..domain.results import PipelineReady
from ..pipeline.evidence import parse_canonical_input_digest
from ..pipeline.orchestrator import run_offline_pipeline
from .idempotency import existing_bundle_identity
from .layout import ArtifactWriteError


def normalize_and_match_input(root: Path, canonical: bytes, ready: PipelineReady) -> bytes:
    try:
        value = parse_json(canonical)
        normalized = encode_json_bytes(value)
        decoded = decode_offline_run_request(value)
    except JsonDecodeError as error:
        raise ArtifactWriteError(
            "CONTRACT_INVALID", error.issue.pointer, error.issue.message
        ) from error
    if normalized != canonical or decoded != ready.request:
        raise ArtifactWriteError(
            "CONTRACT_INVALID", "/canonical_input",
            "canonical input must be normalized and match the pipeline request",
        )
    digest = parse_canonical_input_digest(sha256(normalized).hexdigest())
    if run_offline_pipeline(root, decoded, digest) != ready:
        raise ArtifactWriteError(
            "CONTRACT_INVALID", "/pipeline_result",
            "pipeline result must match deterministic evaluation of the input",
        )
    return normalized


def validate_existing_package(
    bundle: Path, payloads: Mapping[str, bytes], manifest: PublishManifest,
) -> None:
    package_id, key, _ = existing_bundle_identity(bundle)
    if key != manifest.idempotency_key or package_id != manifest.package_id:
        raise ArtifactWriteError(
            "IDEMPOTENCY_CONFLICT", "/idempotency_key",
            "existing key is bound to different normalized inputs",
        )
    entries = tuple(bundle.iterdir())
    if {item.name for item in entries} != set(payloads):
        raise ArtifactWriteError(
            "REVIEW_OUTPUT_CHANGED", "/bundle", "reviewed artifact set has changed",
        )
    for item in entries:
        if item.is_symlink() or not item.is_file() or item.read_bytes() != payloads[item.name]:
            raise ArtifactWriteError(
                "REVIEW_OUTPUT_CHANGED", f"/bundle/{item.name}",
                "stored artifact does not match the reviewed bytes",
            )
