from pathlib import Path

from tistory_growth_os.delivery.new_reservation_execution import NewReservationExecutor
from tistory_growth_os.delivery.reservation_execution import ExecutionState
from tistory_growth_os.delivery.reservation_readback import DailySlot
from tistory_growth_os.delivery.save_intents import SaveIntentJournal
from tests.test_new_reservation_execution import NewSurface
from tests.test_new_reservation_identity import intent


def test_save_receipt_persisted_before_readback(tmp_path: Path) -> None:
    path = tmp_path / 'journal.db'
    first = NewReservationExecutor(SaveIntentJournal(path), NewSurface(missing_readback=True))
    result = first.run(intent(), dry_run=False)
    assert result.execution.state is ExecutionState.UNKNOWN
    assert SaveIntentJournal(path).receipt(DailySlot(intent().scheduled_at).key, intent().package_digest) is not None


def test_recovery_reads_same_identity_without_writes(tmp_path: Path) -> None:
    path = tmp_path / 'journal.db'
    _ = NewReservationExecutor(SaveIntentJournal(path), NewSurface()).run(intent(), dry_run=False)
    surface = NewSurface()
    recovered = NewReservationExecutor(SaveIntentJournal(path), surface).recover(intent())
    assert recovered.execution.state is ExecutionState.VERIFIED
    assert surface.calls == ['readback']
    assert recovered.target is not None and recovered.target.post_id == '92'


def test_missing_receipt_cannot_trigger_new_save(tmp_path: Path) -> None:
    surface = NewSurface()
    result = NewReservationExecutor(SaveIntentJournal(tmp_path / 'journal.db'), surface).recover(intent())
    assert result.execution.state is ExecutionState.UNKNOWN
    assert surface.calls == []


def test_recovery_does_not_trust_previous_success(tmp_path: Path) -> None:
    path = tmp_path / 'journal.db'
    _ = NewReservationExecutor(SaveIntentJournal(path), NewSurface()).run(intent(), dry_run=False)
    surface = NewSurface(wrong_body=True)
    result = NewReservationExecutor(SaveIntentJournal(path), surface).recover(intent())
    assert result.execution.state is ExecutionState.MISMATCH
    assert surface.calls == ['readback']


def test_kill_switch_blocks_recovery_readback(tmp_path: Path) -> None:
    path = tmp_path / 'journal.db'
    _ = NewReservationExecutor(SaveIntentJournal(path), NewSurface()).run(intent(), dry_run=False)
    surface = NewSurface(calls=['prepare'], stop_after_prepare=True)
    result = NewReservationExecutor(SaveIntentJournal(path), surface).recover(intent())
    assert result.execution.state is ExecutionState.BLOCKED
    assert surface.calls == ['prepare']


def test_release_time_requires_separate_public_check(tmp_path: Path) -> None:
    path = tmp_path / 'journal.db'
    _ = NewReservationExecutor(SaveIntentJournal(path), NewSurface()).run(intent(), dry_run=False)
    surface = NewSurface(calls=['prepare'], expire_after_prepare=True)
    result = NewReservationExecutor(SaveIntentJournal(path), surface).recover(intent())
    assert result.execution.state is ExecutionState.UNKNOWN
    assert result.execution.reasons == ('release_check_required',)
    assert surface.calls == ['prepare', 'readback']
