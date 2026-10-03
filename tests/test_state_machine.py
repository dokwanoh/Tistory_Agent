from __future__ import annotations

from typing import Final

from tistory_growth_os.domain.state import (
    STATE_TRANSITION_INVALID,
    PipelineEvent,
    PipelineState,
    TransitionAccepted,
    TransitionRejected,
    transition,
)


ACTIVE_STATES = (
    PipelineState.TOPIC_VALIDATED,
    PipelineState.EVIDENCE_READY,
    PipelineState.BRIEF_READY,
    PipelineState.DRAFT_READY,
    PipelineState.QUALITY_PASSED,
)
TERMINAL_STATES = (
    PipelineState.READY_FOR_APPROVAL,
    PipelineState.BLOCKED,
    PipelineState.INVALID,
)
HAPPY_PATH = (
    PipelineEvent.EVIDENCE_READY,
    PipelineEvent.BRIEF_READY,
    PipelineEvent.DRAFT_READY,
    PipelineEvent.QUALITY_PASSED,
    PipelineEvent.PACKAGE_READY,
)
HAPPY_TARGETS = (
    PipelineState.EVIDENCE_READY,
    PipelineState.BRIEF_READY,
    PipelineState.DRAFT_READY,
    PipelineState.QUALITY_PASSED,
    PipelineState.READY_FOR_APPROVAL,
)
PROGRESSION_TARGETS: Final[dict[tuple[PipelineState, PipelineEvent], PipelineState]] = dict(zip(
    zip(
        (
            PipelineState.TOPIC_VALIDATED,
            PipelineState.EVIDENCE_READY,
            PipelineState.BRIEF_READY,
            PipelineState.DRAFT_READY,
            PipelineState.QUALITY_PASSED,
        ),
        HAPPY_PATH,
        strict=True,
    ),
    HAPPY_TARGETS,
    strict=True,
))
CONTRACT_FAILURE_TARGETS: Final[dict[tuple[PipelineState, PipelineEvent], PipelineState]] = {
    (state, PipelineEvent.CONTRACT_FAILED): PipelineState.INVALID
    for state in ACTIVE_STATES
}
BLOCKING_FAILURE_TARGETS: Final[dict[tuple[PipelineState, PipelineEvent], PipelineState]] = {
    (state, event): PipelineState.BLOCKED
    for state in ACTIVE_STATES
    for event in (PipelineEvent.POLICY_FAILED, PipelineEvent.QUALITY_FAILED)
}
EXPECTED_TARGETS: Final[dict[tuple[PipelineState, PipelineEvent], PipelineState]] = {
    **PROGRESSION_TARGETS,
    **CONTRACT_FAILURE_TARGETS,
    **BLOCKING_FAILURE_TARGETS,
}


def _expected_target(
    state: PipelineState,
    event: PipelineEvent,
) -> PipelineState | None:
    return EXPECTED_TARGETS.get((state, event))


def test_happy_path_has_exact_ordered_history() -> None:
    state = PipelineState.TOPIC_VALIDATED
    history = [state]

    for event, expected in zip(HAPPY_PATH, HAPPY_TARGETS, strict=True):
        result = transition(state, event)
        assert isinstance(result, TransitionAccepted)
        assert result.previous_state is state
        assert result.next_state is expected
        state = result.next_state
        history.append(state)

    assert tuple(history) == (
        PipelineState.TOPIC_VALIDATED,
        PipelineState.EVIDENCE_READY,
        PipelineState.BRIEF_READY,
        PipelineState.DRAFT_READY,
        PipelineState.QUALITY_PASSED,
        PipelineState.READY_FOR_APPROVAL,
    )


def test_every_state_event_pair_has_a_deterministic_outcome() -> None:
    expected_pair_count = len(PipelineState) * len(PipelineEvent)
    observed_pair_count = 0

    for state in PipelineState:
        for event in PipelineEvent:
            observed_pair_count += 1
            expected = _expected_target(state, event)
            result = transition(state, event)

            if expected is None:
                assert isinstance(result, TransitionRejected)
                assert result.state is state
                assert result.code == STATE_TRANSITION_INVALID
                continue

            assert isinstance(result, TransitionAccepted)
            assert result.previous_state is state
            assert result.next_state is expected

    assert observed_pair_count == expected_pair_count


def test_illegal_terminal_and_skipped_transitions_are_rejected_without_recovery() -> None:
    for state in TERMINAL_STATES:
        for event in PipelineEvent:
            result = transition(state, event)
            assert isinstance(result, TransitionRejected)
            assert result.state is state
            assert result.code == STATE_TRANSITION_INVALID

    skipped = transition(PipelineState.TOPIC_VALIDATED, PipelineEvent.DRAFT_READY)
    assert isinstance(skipped, TransitionRejected)
    assert skipped.state is PipelineState.TOPIC_VALIDATED
    assert skipped.code == STATE_TRANSITION_INVALID


def test_state_surface_is_limited_to_offline_milestone_two() -> None:
    assert tuple(PipelineState) == (
        PipelineState.TOPIC_VALIDATED,
        PipelineState.EVIDENCE_READY,
        PipelineState.BRIEF_READY,
        PipelineState.DRAFT_READY,
        PipelineState.QUALITY_PASSED,
        PipelineState.READY_FOR_APPROVAL,
        PipelineState.BLOCKED,
        PipelineState.INVALID,
    )
