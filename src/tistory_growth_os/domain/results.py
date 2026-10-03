from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import TypeAlias

from ..contracts.json_ast import JsonObject
from ..policy.models import PolicyEvaluation

from .content import ArticleDraft, ContentBrief, OfflineRunRequest, SourceEvidence
from .publishing import QualityReport
from .state import PipelineState


@dataclass(frozen=True, slots=True)
class PipelineBlocked:
    request: OfflineRunRequest
    evidence: tuple[SourceEvidence, ...]
    brief: ContentBrief
    draft: ArticleDraft
    policy_evaluation: PolicyEvaluation
    quality_report: QualityReport
    state_history: tuple[PipelineState, ...]
    reason_codes: tuple[str, ...]

    @property
    def external_write_count(self) -> int:
        return 0


@dataclass(frozen=True, slots=True)
class PipelineReady:
    request: OfflineRunRequest
    evidence: tuple[SourceEvidence, ...]
    brief: ContentBrief
    draft: ArticleDraft
    policy_evaluation: PolicyEvaluation
    quality_report: QualityReport
    state_history: tuple[PipelineState, ...]
    body_hash: str
    article_html: str
    metadata: JsonObject
    rollback: JsonObject

    @property
    def external_write_count(self) -> int:
        return 0


PipelineResult: TypeAlias = PipelineBlocked | PipelineReady


@unique
class RunStatus(StrEnum):
    READY_FOR_APPROVAL = "ready_for_approval"
    BLOCKED = "blocked"
    INVALID = "invalid"


@unique
class ResultCode(StrEnum):
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    CLAIM_EVIDENCE_REQUIRED = "CLAIM_EVIDENCE_REQUIRED"
    OWNER_EVIDENCE_REQUIRED = "OWNER_EVIDENCE_REQUIRED"
    CONTRACT_INVALID = "CONTRACT_INVALID"
    POLICY_EVIDENCE_REQUIRED = "POLICY_EVIDENCE_REQUIRED"
    DISCLOSURE_REQUIRED = "DISCLOSURE_REQUIRED"
    PROHIBITED_AD_FORMAT = "PROHIBITED_AD_FORMAT"
    ACCESSIBILITY_REQUIRED = "ACCESSIBILITY_REQUIRED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True, slots=True)
class RunReport:
    run_id: str
    request_id: str
    status: RunStatus
    result_code: ResultCode
    state_history: tuple[str, ...]
    artifact_paths: tuple[str, ...]
    completed_at: datetime

    @property
    def external_write_count(self) -> int:
        return 0
