from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tistory_growth_os.delivery.new_reservation_execution import NewReservationExecutor
from tistory_growth_os.delivery.new_reservation_identity import NewReservationIntent, SavedIdentity
from tistory_growth_os.delivery.reservation_execution import ExecutionState
from tistory_growth_os.delivery.reservation_readback import (
    DailySlot, ReservationObservation, ReservationTarget, SavedVisibility,
)
from tistory_growth_os.delivery.save_intents import SaveIntentJournal
from tistory_growth_os.domain.ids import PostId
from tests.test_new_reservation_identity import identity, intent


@dataclass(frozen=True, slots=True)
class NewSurface:
    calls: list[str] = field(default_factory=list)
    prior: frozenset[PostId] | None = frozenset({PostId("91")})
    receipt: SavedIdentity | None = field(default_factory=identity)
    missing_readback: bool = False
    wrong_body: bool = False
    fail_save: bool = False
    stop_after_prepare: bool = False
    expire_after_prepare: bool = False
    denied: bool = False

    def preparation_fingerprint(self) -> str | None:
        return 'd' * 64

    def now(self) -> datetime:
        if self.expire_after_prepare and "prepare" in self.calls:
            return intent().scheduled_at
        return intent().scheduled_at - timedelta(hours=1)

    def stopped(self) -> bool:
        return self.stop_after_prepare and "prepare" in self.calls

    def authorize(self, request: NewReservationIntent, now: datetime) -> tuple[str, ...]:
        assert request == intent() and now < request.scheduled_at
        self.calls.append("authorize")
        return ("review_denied",) if self.denied else ()

    def inventory(self) -> frozenset[PostId] | None:
        self.calls.append("inventory")
        return self.prior

    def prepare(self, request: NewReservationIntent) -> None:
        assert request == intent()
        self.calls.append("prepare")

    def save(self, request: NewReservationIntent) -> SavedIdentity | None:
        assert request == intent()
        self.calls.append("save")
        if self.fail_save:
            raise TimeoutError()
        return self.receipt

    def readback(self, target: ReservationTarget) -> ReservationObservation | None:
        self.calls.append("readback")
        if self.missing_readback:
            return None
        actual = replace(target, content=replace(target.content, body_digest="c" * 64)) if self.wrong_body else target
        return ReservationObservation(actual, SavedVisibility.SCHEDULED, self.now())


def test_dry_run_has_no_surface_calls(tmp_path: Path) -> None:
    surface = NewSurface()
    journal = SaveIntentJournal(tmp_path / "intent.db")
    result = NewReservationExecutor(journal, surface).run(intent())
    assert result.execution.state is ExecutionState.DRY_RUN
    assert result.target is None and not surface.calls
    assert journal.claim(DailySlot(intent().scheduled_at).key, intent().package_digest)


def test_new_save_binds_observed_identity_and_verifies(tmp_path: Path) -> None:
    surface = NewSurface()
    result = NewReservationExecutor(SaveIntentJournal(tmp_path / "intent.db"), surface).run(intent(), dry_run=False)
    assert result.execution.state is ExecutionState.VERIFIED
    assert result.target is not None and result.target.post_id == "92"
    assert surface.calls.count("save") == 1 and surface.calls[-1] == "readback"


@pytest.mark.parametrize("surface,expected", [
    (NewSurface(receipt=None), ExecutionState.UNKNOWN),
    (NewSurface(receipt=identity("91")), ExecutionState.MISMATCH),
    (NewSurface(missing_readback=True), ExecutionState.UNKNOWN),
    (NewSurface(wrong_body=True), ExecutionState.MISMATCH),
])
def test_uncertain_or_wrong_save_holds_retries(tmp_path: Path, surface: NewSurface, expected: ExecutionState) -> None:
    path = tmp_path / "intent.db"
    result = NewReservationExecutor(SaveIntentJournal(path), surface).run(intent(), dry_run=False)
    assert result.execution.state is expected
    retry = NewSurface()
    replay = NewReservationExecutor(SaveIntentJournal(path), retry).run(intent(), dry_run=False)
    assert replay.execution.state is ExecutionState.HELD
    assert "prepare" not in retry.calls and "save" not in retry.calls


@pytest.mark.parametrize("surface", [NewSurface(prior=None), NewSurface(denied=True)])
def test_missing_inventory_or_authority_prevents_input(tmp_path: Path, surface: NewSurface) -> None:
    result = NewReservationExecutor(SaveIntentJournal(tmp_path / "intent.db"), surface).run(intent(), dry_run=False)
    assert result.execution.state is ExecutionState.BLOCKED
    assert "prepare" not in surface.calls and "save" not in surface.calls


@pytest.mark.parametrize("surface", [NewSurface(stop_after_prepare=True), NewSurface(expire_after_prepare=True)])
def test_gate_rechecked_after_input(tmp_path: Path, surface: NewSurface) -> None:
    result = NewReservationExecutor(SaveIntentJournal(tmp_path / "intent.db"), surface).run(intent(), dry_run=False)
    assert result.execution.state is ExecutionState.BLOCKED
    assert "prepare" in surface.calls and "save" not in surface.calls


def test_timeout_keeps_claim_across_process_restart(tmp_path: Path) -> None:
    path = tmp_path / "intent.db"
    with pytest.raises(TimeoutError):
        _ = NewReservationExecutor(SaveIntentJournal(path), NewSurface(fail_save=True)).run(intent(), dry_run=False)
    retry = NewSurface()
    result = NewReservationExecutor(SaveIntentJournal(path), retry).run(intent(), dry_run=False)
    assert result.execution.state is ExecutionState.HELD
    assert "save" not in retry.calls
