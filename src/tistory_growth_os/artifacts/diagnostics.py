from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Final

from ..contracts.json_ast import (
    JsonBoolean,
    JsonMember,
    JsonNumber,
    JsonObject,
    JsonString,
)
from ..contracts.json_decode import ContractIssue
from ..contracts.json_encode import encode_json_bytes
from ..contracts.registry import ContractRegistry
from ..domain.results import (
    PipelineBlocked,
    ResultCode,
    RunReport,
    RunStatus,
)
from .layout import ArtifactWriteError, safe_output_root
from .serialization import article_draft_json, quality_report_json, run_report_json


_CREDENTIAL_ASSIGNMENT: Final = re.compile(
    r"(?i)\b(password|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
    + r"\s*[:=]\s*[^\s,;\"']+"
)
_AWS_KEY: Final = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_BEARER: Final = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")


@dataclass(frozen=True, slots=True)
class DiagnosticWriteResult:
    output_path: Path
    run_id: str
    external_write_count: int = 0


def write_blocked_diagnostics(
    project_root: Path,
    output_relative: str,
    blocked: PipelineBlocked,
    completed_at: datetime,
) -> DiagnosticWriteResult:
    code = ResultCode(blocked.reason_codes[0])
    run_id = _run_id(blocked.request.request_id, code, completed_at)
    report = RunReport(
        run_id,
        blocked.request.request_id,
        RunStatus.BLOCKED,
        code,
        tuple(item.value for item in blocked.state_history),
        ("quality-report.json", "article-draft.json"),
        completed_at,
    )
    payloads = {
        "article-draft.json": encode_json_bytes(article_draft_json(blocked.draft)),
        "run-report.json": encode_json_bytes(run_report_json(report)),
        "quality-report.json": encode_json_bytes(
            quality_report_json(blocked.quality_report)
        ),
        "audit.jsonl": encode_json_bytes(
            _blocked_audit(blocked.request.request_id, code)
        ),
    }
    _validate_report(project_root, report)
    output = _write_atomic(project_root, output_relative, payloads)
    return DiagnosticWriteResult(output, run_id)


def write_invalid_diagnostics(
    project_root: Path,
    output_relative: str,
    issue: ContractIssue,
    completed_at: datetime,
) -> DiagnosticWriteResult:
    request_id = "request_unknown"
    code = ResultCode.CONTRACT_INVALID
    run_id = _run_id(request_id, code, completed_at)
    report = RunReport(
        run_id,
        request_id,
        RunStatus.INVALID,
        code,
        ("invalid",),
        (),
        completed_at,
    )
    payloads = {
        "run-report.json": encode_json_bytes(run_report_json(report)),
        "audit.jsonl": encode_json_bytes(_invalid_audit(issue)),
    }
    _validate_report(project_root, report)
    output = _write_atomic(project_root, output_relative, payloads)
    return DiagnosticWriteResult(output, run_id)


def _run_id(request_id: str, code: ResultCode, completed_at: datetime) -> str:
    material = f"{request_id}\x00{code.value}\x00{completed_at.isoformat()}"
    return f"run_{sha256(material.encode('utf-8')).hexdigest()}"


def _validate_report(root: Path, report: RunReport) -> None:
    registry = ContractRegistry.load(root / "contracts")
    issues = registry.validate("run-report", run_report_json(report))
    if issues:
        first = issues[0]
        raise ArtifactWriteError("ARTIFACT_SCHEMA_INVALID", first.pointer, first.message)


def _blocked_audit(request_id: str, code: ResultCode) -> JsonObject:
    return JsonObject((
        JsonMember("event", JsonString("pipeline_blocked")),
        JsonMember("request_id", JsonString(request_id)),
        JsonMember("result_code", JsonString(code.value)),
        JsonMember("bundle_created", JsonBoolean(False)),
        JsonMember("external_write_count", JsonNumber(0)),
    ))


def _invalid_audit(issue: ContractIssue) -> JsonObject:
    error = JsonObject((
        JsonMember("code", JsonString("CONTRACT_INVALID")),
        JsonMember("path", JsonString(issue.pointer)),
        JsonMember("message", JsonString(_redact(issue.message))),
        JsonMember("line", JsonNumber(issue.line)),
        JsonMember("column", JsonNumber(issue.column)),
    ))
    return JsonObject((
        JsonMember("event", JsonString("contract_invalid")),
        JsonMember("error", error),
        JsonMember("bundle_created", JsonBoolean(False)),
        JsonMember("external_write_count", JsonNumber(0)),
    ))


def _redact(value: str) -> str:
    redacted = _CREDENTIAL_ASSIGNMENT.sub(r"\1=<redacted>", value)
    redacted = _AWS_KEY.sub("<redacted>", redacted)
    return _BEARER.sub("Bearer <redacted>", redacted)


def _write_atomic(
    project_root: Path,
    output_relative: str,
    payloads: dict[str, bytes],
) -> Path:
    diagnostic_relative = PurePosixPath(output_relative) / "diagnostics"
    output = safe_output_root(project_root, diagnostic_relative.as_posix())
    if output.exists() or output.is_symlink():
        raise ArtifactWriteError(
            "OUTPUT_ALREADY_EXISTS",
            "/output",
            "diagnostic output already exists",
        )
    parent = output.parent
    _ = parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".diagnostic-staging-", dir=parent))
    try:
        for name, body in payloads.items():
            _ = (staging / name).write_bytes(body)
        _ = os.replace(staging, output)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output
