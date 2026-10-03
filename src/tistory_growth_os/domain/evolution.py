from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum, unique
from typing import final

from .ids import EvolutionProposalId, ExperimentId, PostId


@final
class EvolutionInvariantError(ValueError):
    __slots__ = ("code", "path", "message")

    code: str
    path: str
    message: str

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


@unique
class ExperimentStatus(StrEnum):
    PROPOSED = "proposed"
    SHADOW = "shadow"
    CANARY = "canary"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class Experiment:
    experiment_id: ExperimentId
    post_ids: tuple[PostId, ...]
    hypothesis: str
    controllable_factor: str
    primary_metric: str
    acceptance_threshold: Decimal
    status: ExperimentStatus
    started_at: datetime
    observation_end: datetime
    rollback_condition: str

    def __post_init__(self) -> None:
        if not self.post_ids or not self.controllable_factor or not self.rollback_condition:
            raise EvolutionInvariantError(
                "CONTRACT_INVALID",
                "/",
                "experiment requires scope, one factor, and rollback",
            )
        if self.observation_end < self.started_at:
            raise EvolutionInvariantError(
                "CONTRACT_INVALID",
                "/observation_end",
                "observation cannot end before start",
            )


@unique
class BDWClass(StrEnum):
    BOTTLENECK = "bottleneck"
    DELAY = "delay"
    WASTE = "waste"


@unique
class ChangeTarget(StrEnum):
    PROMPT = "prompt"
    MODEL = "model"
    REASONING = "reasoning"
    TOOL = "tool"
    HARNESS = "harness"
    WORKFLOW = "workflow"
    SCHEMA = "schema"
    POLICY = "policy"


@unique
class EvolutionDecision(StrEnum):
    PENDING = "pending"
    PROMOTE = "promote"
    REJECT = "reject"
    ROLLBACK = "rollback"


@dataclass(frozen=True, slots=True)
class EvolutionProposal:
    proposal_id: EvolutionProposalId
    observed_trace_id: str
    bdw_class: BDWClass
    root_cause_hypothesis: str
    change_target: ChangeTarget
    expected_effect: str
    regression_risk: str
    eval_ids: tuple[str, ...]
    acceptance_threshold: Decimal
    cost_budget_krw: Decimal
    latency_budget_seconds: Decimal
    canary_scope: str
    rollback_condition: str
    decision: EvolutionDecision
    owner_approval_required: bool
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not self.eval_ids or self.cost_budget_krw < 0 or self.latency_budget_seconds < 0:
            raise EvolutionInvariantError(
                "CONTRACT_INVALID",
                "/",
                "evaluation and non-negative budgets are required",
            )
        match self.change_target:
            case ChangeTarget.POLICY | ChangeTarget.SCHEMA:
                protected = True
            case (
                ChangeTarget.PROMPT
                | ChangeTarget.MODEL
                | ChangeTarget.REASONING
                | ChangeTarget.TOOL
                | ChangeTarget.HARNESS
                | ChangeTarget.WORKFLOW
            ):
                protected = False
        if protected and not self.owner_approval_required:
            raise EvolutionInvariantError(
                "OWNER_APPROVAL_REQUIRED",
                "/owner_approval_required",
                "policy, rights, and contract thresholds cannot be weakened automatically",
            )
