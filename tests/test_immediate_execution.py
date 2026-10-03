from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tistory_growth_os.delivery.immediate_execution import ImmediateExecutor, ImmediateIntent, ImmediateJournal
from tistory_growth_os.delivery.immediate_readback import ImmediateObservation, ImmediateTarget
from tistory_growth_os.delivery.immediate_media import MediaBinding
from tistory_growth_os.delivery.new_reservation_identity import SavedIdentity
from tistory_growth_os.delivery.reservation_execution import ExecutionState
from tistory_growth_os.delivery.reservation_readback import ReservationContent, ReservationMedia, SavedVisibility
from tistory_growth_os.domain.ids import MediaId, PostId


def intent_fixture() -> ImmediateIntent:
    content = ReservationContent('검수 제목', 'a' * 64,
        tuple(ReservationMedia(MediaId(str(i)), f'사진 {i}') for i in range(4)),
        MediaId('0'), '생활정보', '국내여행', ('여행',))
    return ImmediateIntent('manual-one', content, 'b' * 64,
                           datetime.fromisoformat('2030-01-01T17:00:00+09:00'))


class Surface:
    def __init__(self, case: str) -> None:
        self.case: str = case
        self.prepares: int = 0
        self.saves: int = 0

    def now(self) -> datetime:
        now = datetime.fromisoformat('2030-01-01T15:00:30+09:00')
        return now + timedelta(hours=3) if self.case == 'late_publication' and self.saves else now

    def stopped(self) -> bool:
        return self.case == 'stop' or self.case == 'stop_after_prepare' and self.prepares > 0

    def authorize(self, request: ImmediateIntent, now: datetime) -> tuple[str, ...]:
        assert request.operation_id == 'manual-one' and now.utcoffset() is not None
        return ('approval_required',) if self.case == 'denied' else ()

    def inventory(self) -> frozenset[PostId] | None:
        return None if self.case == 'inventory' else frozenset((PostId('1'),))

    def prepare(self, request: ImmediateIntent) -> None:
        assert request.operation_id == 'manual-one'
        self.prepares += 1

    def save(self, request: ImmediateIntent) -> SavedIdentity | None:
        assert request.operation_id == 'manual-one'
        self.saves += 1
        if self.case == 'unknown':
            return None
        identity = '1' if self.case == 'preexisting' else '2'
        return SavedIdentity(PostId(identity), f'https://example.tistory.com/{identity}')

    def readback(self, target: ImmediateTarget) -> ImmediateObservation:
        return ImmediateObservation(target.identity, target.content, SavedVisibility.PUBLIC,
            self.now() - timedelta(seconds=30), self.now(), self.case != 'anonymous')


@pytest.mark.parametrize(('case', 'expected', 'saves'), [
    ('valid', ExecutionState.VERIFIED, 1), ('dry_run', ExecutionState.DRY_RUN, 0),
    ('stop', ExecutionState.BLOCKED, 0), ('denied', ExecutionState.BLOCKED, 0),
    ('inventory', ExecutionState.BLOCKED, 0), ('stop_after_prepare', ExecutionState.BLOCKED, 0),
    ('unknown', ExecutionState.UNKNOWN, 1), ('preexisting', ExecutionState.MISMATCH, 1),
    ('anonymous', ExecutionState.MISMATCH, 1),
    ('late_publication', ExecutionState.MISMATCH, 1),
])
def test_immediate_executor_when_boundaries_change(case: str, expected: ExecutionState, saves: int, tmp_path: Path) -> None:
    # Given: a real durable journal and a single immediate intent without a daily slot.
    surface = Surface(case)
    journal = ImmediateJournal(tmp_path / 'journal.sqlite3')
    request = intent_fixture()
    # When: running the same executor used by the CLI.
    result = ImmediateExecutor(journal, surface).run(request, dry_run=case == 'dry_run')
    # Then: only observed anonymous publication is verified; replay never saves twice.
    assert result.execution.state is expected
    assert surface.saves == saves
    if saves:
        replay = ImmediateExecutor(ImmediateJournal(tmp_path / 'journal.sqlite3'), surface).run(request, dry_run=False)
        assert replay.execution.state is (ExecutionState.BLOCKED if case == 'late_publication' else ExecutionState.HELD)
        assert surface.saves == 1
    if case == 'valid':
        recovered = ImmediateExecutor(ImmediateJournal(tmp_path / 'journal.sqlite3'), surface).recover(request)
        assert recovered.execution.state is ExecutionState.VERIFIED
        assert surface.saves == 1


def test_durable_media_binding_rejects_changes_and_contains_no_source_urls(tmp_path: Path) -> None:
    journal = ImmediateJournal(tmp_path / 'journal.sqlite3')
    request = intent_fixture()
    bindings = tuple(MediaBinding(MediaId(str(i)), f'{i}.jpg', str(i) * 64) for i in range(4))
    with pytest.raises(ValueError):
        journal.media.record(request.key, request.package_digest, bindings)
    assert journal.saves.claim(request.key, request.package_digest)
    journal.media.record(request.key, request.package_digest, bindings)
    fresh = ImmediateJournal(tmp_path / 'journal.sqlite3')
    assert fresh.media.read(request.key, request.package_digest) == bindings
    changed = (MediaBinding(MediaId('0'), '0.jpg', 'f' * 64), *bindings[1:])
    with pytest.raises(ValueError):
        journal.media.record(request.key, request.package_digest, changed)
    journal.start(request, Surface('valid').now())
    with pytest.raises(ValueError):
        journal.media.record(request.key, request.package_digest, bindings)
