from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from ..artifacts.diagnostics import (
    write_blocked_diagnostics,
    write_invalid_diagnostics,
)
from ..artifacts.layout import ArtifactWriteError, safe_output_root
from ..artifacts.writer import write_approval_bundle
from ..contracts.json_ast import JsonMember, JsonNumber, JsonObject, JsonString
from ..contracts.json_decode import JsonDecodeError, parse_json_file
from ..contracts.json_encode import encode_json_bytes
from ..domain.content_request_decode import decode_offline_run_request
from ..domain.results import PipelineBlocked, PipelineReady
from ..pipeline.evidence import parse_canonical_input_digest
from ..pipeline.orchestrator import run_offline_pipeline

from .args import RunArgs


def execute_run(args: RunArgs) -> tuple[int, JsonObject]:
    root = args.root.resolve()
    try:
        fixture = _fixture_path(root, args.fixture)
        value = parse_json_file(fixture)
        canonical = encode_json_bytes(value)
        request = decode_offline_run_request(value)
        digest = parse_canonical_input_digest(sha256(canonical).hexdigest())
        result = run_offline_pipeline(root, request, digest)
        match result:
            case PipelineReady():
                written = write_approval_bundle(root, args.output, result, canonical)
                return 0, _success_json(
                    written.bundle_path.relative_to(root).as_posix(),
                    written.package_id,
                    written.manifest_id,
                )
            case PipelineBlocked():
                written = write_blocked_diagnostics(
                    root,
                    args.output,
                    result,
                    result.quality_report.evaluated_at,
                )
                return 2, _result_json(
                    "blocked",
                    result.reason_codes[0],
                    written.output_path.relative_to(root).as_posix(),
                )
    except JsonDecodeError as error:
        written = write_invalid_diagnostics(
            root,
            args.output,
            error.issue,
            datetime.now(timezone.utc),
        )
        return 2, _result_json(
            "invalid",
            "CONTRACT_INVALID",
            written.output_path.relative_to(root).as_posix(),
        )
    except ArtifactWriteError as error:
        artifact_path = ""
        if error.path == "/review":
            output = safe_output_root(root, args.output)
            artifact_path = (output / "review-audit.jsonl").relative_to(root).as_posix()
        return 2, _result_json("blocked", error.code, artifact_path)


def _fixture_path(root: Path, relative: str) -> Path:
    path = safe_output_root(root, relative)
    if not path.is_file():
        raise ArtifactWriteError(
            "FIXTURE_NOT_FOUND", "/fixture", "fixture must be a regular file"
        )
    return path


def _result_json(status: str, code: str, artifact_path: str) -> JsonObject:
    return JsonObject((
        JsonMember("status", JsonString(status)),
        JsonMember("result_code", JsonString(code)),
        JsonMember("artifact_path", JsonString(artifact_path)),
        JsonMember("external_write_count", JsonNumber(0)),
    ))


def _success_json(
    bundle_path: str,
    package_id: str,
    manifest_id: str,
) -> JsonObject:
    return JsonObject((
        JsonMember("status", JsonString("READY_FOR_APPROVAL")),
        JsonMember("result_code", JsonString("READY_FOR_APPROVAL")),
        JsonMember("package_id", JsonString(package_id)),
        JsonMember("manifest_id", JsonString(manifest_id)),
        JsonMember("bundle_path", JsonString(bundle_path)),
        JsonMember("external_write_count", JsonNumber(0)),
    ))
