from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


AuditStatus: TypeAlias = Literal["pass", "fail"]


@dataclass(frozen=True, slots=True)
class RequiredDocumentsReport:
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TraceabilityReport:
    missing: tuple[str, ...]
    duplicates: tuple[str, ...]
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContractsReport:
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicyEvidenceReport:
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OwnerDecisionsReport:
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OfflineBoundaryReport:
    external_adapters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceHygieneReport:
    violations: tuple[str, ...]
    oversized_modules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SecretMatch:
    path: str
    line: int
    kind: str
    redacted: str = "<redacted>"


@dataclass(frozen=True, slots=True)
class SecretsReport:
    matches: tuple[SecretMatch, ...]


@dataclass(frozen=True, slots=True)
class ProjectAuditReport:
    status: AuditStatus
    required_documents: RequiredDocumentsReport
    traceability: TraceabilityReport
    contracts: ContractsReport
    policy_evidence: PolicyEvidenceReport
    owner_decisions: OwnerDecisionsReport
    offline_boundary: OfflineBoundaryReport
    source_hygiene: SourceHygieneReport
    secrets: SecretsReport
