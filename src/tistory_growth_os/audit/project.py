from __future__ import annotations

from pathlib import Path
from typing import Final

from .catalogs import audit_contracts, audit_owner_decisions, audit_policy_evidence, audit_traceability
from .models import ProjectAuditReport, RequiredDocumentsReport
from .secrets import audit_secrets
from .source import audit_source


_REQUIRED_DOCUMENTS: Final = (
    "AGENTS.md",
    "PROJECT_SPEC.md",
    "PLAN.md",
    "STATUS.md",
    "DECISIONS.md",
    "RISKS.md",
    "METRICS.md",
    "BACKLOG.md",
    "OWNER_INPUT.md",
    "DESIGN.md",
    "docs/01_as_is.md",
    "docs/02_bdw_analysis.md",
    "docs/03_erask_transition.md",
    "docs/04_to_be.md",
    "docs/05_architecture.md",
    "docs/06_tdd_and_evals.md",
    "docs/07_security_policy_compliance.md",
    "docs/08_delivery_roadmap.md",
)


def audit_project(root: Path) -> ProjectAuditReport:
    canonical_root = root.resolve()
    required = RequiredDocumentsReport(_missing_documents(canonical_root))
    traceability = audit_traceability(canonical_root)
    contracts = audit_contracts(canonical_root)
    policy = audit_policy_evidence(canonical_root)
    owners = audit_owner_decisions(canonical_root)
    source = audit_source(canonical_root)
    secrets = audit_secrets(canonical_root)
    clean = not (
        required.missing
        or traceability.missing
        or traceability.duplicates
        or traceability.issues
        or contracts.issues
        or policy.missing
        or owners.issues
        or source.boundary.external_adapters
        or source.hygiene.violations
        or source.hygiene.oversized_modules
        or secrets.matches
    )
    return ProjectAuditReport(
        status="pass" if clean else "fail",
        required_documents=required,
        traceability=traceability,
        contracts=contracts,
        policy_evidence=policy,
        owner_decisions=owners,
        offline_boundary=source.boundary,
        source_hygiene=source.hygiene,
        secrets=secrets,
    )


def _missing_documents(root: Path) -> tuple[str, ...]:
    return tuple(relative for relative in _REQUIRED_DOCUMENTS if not _safe_file(root, relative))


def _safe_file(root: Path, relative: str) -> bool:
    path = root / relative
    if not path.is_file():
        return False
    try:
        _ = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True
