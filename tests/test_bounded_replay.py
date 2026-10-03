from pathlib import Path

from tests.test_immediate_execution import Surface, intent_fixture
from tistory_growth_os.delivery.immediate_execution import ImmediateExecutor, ImmediateJournal
from tistory_growth_os.delivery.reservation_execution import ExecutionState


def test_same_identity_when_interrupted_before_save_never_reenters(tmp_path: Path) -> None:
    surface = Surface('stop_after_prepare')
    journal_path = tmp_path / 'journal.sqlite3'
    request = intent_fixture()
    first = ImmediateExecutor(ImmediateJournal(journal_path), surface).run(request, dry_run=False)
    assert first.execution.state is ExecutionState.BLOCKED
    assert surface.saves == 0
    surface.case = 'valid'
    replay = ImmediateExecutor(ImmediateJournal(journal_path), surface).run(request, dry_run=False)
    assert replay.execution.state is ExecutionState.HELD
    assert replay.execution.reasons == ('existing_intent',)
    assert surface.saves == 0
    assert surface.prepares == 1
