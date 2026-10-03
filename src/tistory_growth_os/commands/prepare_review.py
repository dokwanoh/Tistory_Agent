from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import assert_never

from ..artifacts.diagnostics import write_blocked_diagnostics, write_invalid_diagnostics
from ..artifacts.layout import ArtifactWriteError, safe_output_root
from ..artifacts.writer import review_candidate_json
from ..contracts.json_ast import JsonMember, JsonNumber, JsonObject, JsonString
from ..contracts.json_decode import JsonDecodeError, parse_json_file
from ..contracts.json_encode import encode_json_bytes
from ..domain.content_request_decode import decode_offline_run_request
from ..domain.results import PipelineBlocked, PipelineReady
from ..pipeline.evidence import parse_canonical_input_digest
from ..pipeline.orchestrator import run_offline_pipeline
from .args import RunArgs
from .output import write_optional_json


def execute_prepare_review(args: RunArgs) -> tuple[int, JsonObject]:
    root = args.root.resolve()
    if not args.dry_run:
        raise ArtifactWriteError("CLI_USAGE_INVALID", "/dry_run", "inspection requires dry-run")
    try:
        fixture = safe_output_root(root, args.fixture)
        if not fixture.is_file():
            raise ArtifactWriteError("FIXTURE_NOT_FOUND", "/fixture", "fixture must be a regular file")
        value = parse_json_file(fixture)
        canonical = encode_json_bytes(value)
        digest = parse_canonical_input_digest(sha256(canonical).hexdigest())
        result = run_offline_pipeline(root, decode_offline_run_request(value), digest)
        match result:
            case PipelineReady():
                candidate = review_candidate_json(root, result, canonical)
                path = safe_output_root(root, f"{args.output}/review-candidate.json")
                if path.exists():
                    raise ArtifactWriteError("OUTPUT_EXISTS", "/output", "preserve previous inspection; use a new output")
                relative = path.relative_to(root).as_posix()
                write_optional_json(root, relative, candidate)
                return 0, _response("REVIEW_REQUIRED", "REVIEW_CANDIDATE_CREATED", relative)
            case PipelineBlocked():
                written = write_blocked_diagnostics(root, args.output, result, result.quality_report.evaluated_at)
                return 2, _response("blocked", result.reason_codes[0], written.output_path.relative_to(root).as_posix())
            case _:
                assert_never(result)
    except JsonDecodeError as error:
        invalid = write_invalid_diagnostics(root, args.output, error.issue, datetime.now(timezone.utc))
        return 2, _response("invalid", "CONTRACT_INVALID", invalid.output_path.relative_to(root).as_posix())


def _response(status: str, code: str, path: str) -> JsonObject:
    return JsonObject((
        JsonMember("status", JsonString(status)),
        JsonMember("result_code", JsonString(code)),
        JsonMember("artifact_path", JsonString(path)),
        JsonMember("external_write_count", JsonNumber(0)),
    ))
