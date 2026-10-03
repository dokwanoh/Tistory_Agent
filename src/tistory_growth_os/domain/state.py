from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, TypeAlias, assert_never


STATE_TRANSITION_INVALID: Final = "STATE_TRANSITION_INVALID"
STATE_TRANSITION_ACCEPTED: Final = "STATE_TRANSITION_ACCEPTED"


@unique
class PipelineState(StrEnum):
    TOPIC_VALIDATED = "topic_validated"
    EVIDENCE_READY = "evidence_ready"
    BRIEF_READY = "brief_ready"
    DRAFT_READY = "draft_ready"
    QUALITY_PASSED = "quality_passed"
    READY_FOR_APPROVAL = "ready_for_approval"
    BLOCKED = "blocked"
    INVALID = "invalid"


@unique
class PipelineEvent(StrEnum):
    EVIDENCE_READY = "evidence_ready"
    BRIEF_READY = "brief_ready"
    DRAFT_READY = "draft_ready"
    QUALITY_PASSED = "quality_passed"
    PACKAGE_READY = "package_ready"
    CONTRACT_FAILED = "contract_failed"
    POLICY_FAILED = "policy_failed"
    QUALITY_FAILED = "quality_failed"


@dataclass(frozen=True, slots=True)
class TransitionAccepted:
    previous_state: PipelineState
    event: PipelineEvent
    next_state: PipelineState
    code: str = STATE_TRANSITION_ACCEPTED


@dataclass(frozen=True, slots=True)
class TransitionRejected:
    state: PipelineState
    event: PipelineEvent
    code: str = STATE_TRANSITION_INVALID


TransitionResult: TypeAlias = TransitionAccepted | TransitionRejected
TransitionTarget: TypeAlias = PipelineState | None


@dataclass(frozen=True, slots=True)
class TransitionRow:
    state: PipelineState
    evidence_ready: TransitionTarget
    brief_ready: TransitionTarget
    draft_ready: TransitionTarget
    quality_passed: TransitionTarget
    package_ready: TransitionTarget
    contract_failed: TransitionTarget
    policy_failed: TransitionTarget
    quality_failed: TransitionTarget


TRANSITION_TABLE: Final = (
    TransitionRow(PipelineState.TOPIC_VALIDATED, PipelineState.EVIDENCE_READY, None, None, None, None, PipelineState.INVALID, PipelineState.BLOCKED, PipelineState.BLOCKED),
    TransitionRow(PipelineState.EVIDENCE_READY, None, PipelineState.BRIEF_READY, None, None, None, PipelineState.INVALID, PipelineState.BLOCKED, PipelineState.BLOCKED),
    TransitionRow(PipelineState.BRIEF_READY, None, None, PipelineState.DRAFT_READY, None, None, PipelineState.INVALID, PipelineState.BLOCKED, PipelineState.BLOCKED),
    TransitionRow(PipelineState.DRAFT_READY, None, None, None, PipelineState.QUALITY_PASSED, None, PipelineState.INVALID, PipelineState.BLOCKED, PipelineState.BLOCKED),
    TransitionRow(PipelineState.QUALITY_PASSED, None, None, None, None, PipelineState.READY_FOR_APPROVAL, PipelineState.INVALID, PipelineState.BLOCKED, PipelineState.BLOCKED),
    TransitionRow(PipelineState.READY_FOR_APPROVAL, None, None, None, None, None, None, None, None),
    TransitionRow(PipelineState.BLOCKED, None, None, None, None, None, None, None, None),
    TransitionRow(PipelineState.INVALID, None, None, None, None, None, None, None, None),
)


def transition(state: PipelineState, event: PipelineEvent) -> TransitionResult:
    target = _event_target(_row_for(state), event)
    match target:
        case PipelineState() as next_state:
            return TransitionAccepted(
                previous_state=state,
                event=event,
                next_state=next_state,
            )
        case None:
            return TransitionRejected(state=state, event=event)
    assert_never(target)


def _row_for(state: PipelineState) -> TransitionRow:
    match state:
        case PipelineState.TOPIC_VALIDATED:
            return TRANSITION_TABLE[0]
        case PipelineState.EVIDENCE_READY:
            return TRANSITION_TABLE[1]
        case PipelineState.BRIEF_READY:
            return TRANSITION_TABLE[2]
        case PipelineState.DRAFT_READY:
            return TRANSITION_TABLE[3]
        case PipelineState.QUALITY_PASSED:
            return TRANSITION_TABLE[4]
        case PipelineState.READY_FOR_APPROVAL:
            return TRANSITION_TABLE[5]
        case PipelineState.BLOCKED:
            return TRANSITION_TABLE[6]
        case PipelineState.INVALID:
            return TRANSITION_TABLE[7]
    assert_never(state)


def _event_target(row: TransitionRow, event: PipelineEvent) -> TransitionTarget:
    match event:
        case PipelineEvent.EVIDENCE_READY:
            return row.evidence_ready
        case PipelineEvent.BRIEF_READY:
            return row.brief_ready
        case PipelineEvent.DRAFT_READY:
            return row.draft_ready
        case PipelineEvent.QUALITY_PASSED:
            return row.quality_passed
        case PipelineEvent.PACKAGE_READY:
            return row.package_ready
        case PipelineEvent.CONTRACT_FAILED:
            return row.contract_failed
        case PipelineEvent.POLICY_FAILED:
            return row.policy_failed
        case PipelineEvent.QUALITY_FAILED:
            return row.quality_failed
    assert_never(event)
