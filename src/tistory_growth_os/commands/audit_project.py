from __future__ import annotations

from pathlib import Path

from ..audit.models import ProjectAuditReport
from ..audit.project import audit_project
from ..contracts.json_ast import (
    JsonArray,
    JsonMember,
    JsonNumber,
    JsonObject,
    JsonString,
)


def audit_project_json(root: Path) -> JsonObject:
    return _audit_json(audit_project(root))


def _audit_json(report: ProjectAuditReport) -> JsonObject:
    return JsonObject((
        JsonMember("status", JsonString(report.status)),
        _strings("missing_documents", report.required_documents.missing),
        _strings("missing_traceability", report.traceability.missing),
        _strings("duplicate_traceability", report.traceability.duplicates),
        _strings("traceability_issues", report.traceability.issues),
        _strings("contract_issues", report.contracts.issues),
        _strings("missing_policy_evidence", report.policy_evidence.missing),
        _strings("owner_decision_issues", report.owner_decisions.issues),
        _strings("external_adapters", report.offline_boundary.external_adapters),
        _strings("source_violations", report.source_hygiene.violations),
        _strings("oversized_modules", report.source_hygiene.oversized_modules),
        JsonMember("secret_match_count", JsonNumber(len(report.secrets.matches))),
        JsonMember("external_write_count", JsonNumber(0)),
    ))


def _strings(key: str, values: tuple[str, ...]) -> JsonMember:
    return JsonMember(key, JsonArray(tuple(JsonString(item) for item in values)))
