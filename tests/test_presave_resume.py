from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import pytest
from typing_extensions import override

from tistory_growth_os.delivery.new_reservation_execution import NewReservationExecutor
from tistory_growth_os.delivery.new_reservation_identity import NewReservationIntent
from tistory_growth_os.delivery.reservation_execution import ExecutionState
from tistory_growth_os.delivery.reservation_readback import DailySlot
from tistory_growth_os.delivery.save_intents import SaveIntentJournal
from tistory_growth_os.domain.ids import PostId
from tests.test_new_reservation_execution import NewSurface
from tests.test_new_reservation_identity import intent


@dataclass(frozen=True, slots=True)
class ResumableSurface(NewSurface):
    fingerprint: str | None = 'd' * 64
    interrupt_input: bool = False

    @override
    def authorize(self, request: NewReservationIntent, now: datetime) -> tuple[str, ...]:
        if request.package_digest != intent().package_digest:
            return ()
        return NewSurface.authorize(self, request, now)

    @override
    def preparation_fingerprint(self) -> str | None:
        self.calls.append('reconcile')
        return self.fingerprint

    @override
    def prepare(self, request: NewReservationIntent) -> None:
        NewSurface.prepare(self, request)
        if self.interrupt_input:
            raise TimeoutError('input interrupted')


def test_before_input_failure_resumes_same_claim(tmp_path: Path) -> None:
    # Given: no input began because inventory was unavailable.
    path = tmp_path / 'journal.db'
    journal = SaveIntentJournal(path)
    _ = NewReservationExecutor(journal, ResumableSurface(prior=None)).run(intent(), dry_run=False)
    surface = ResumableSurface()
    # When: an explicit resume uses the durable original claim.
    result = NewReservationExecutor(SaveIntentJournal(path), surface).resume(intent(), dry_run=False)
    # Then: one preparation/save succeeds, without freeing the slot.
    assert result.execution.state is ExecutionState.VERIFIED
    assert surface.calls.count('prepare') == surface.calls.count('save') == 1
    assert not journal.claim(DailySlot(intent().scheduled_at).key, intent().package_digest)


def test_prepared_resume_does_not_repeat_input(tmp_path: Path) -> None:
    # Given: preparation completed but the kill switch stopped final save.
    path = tmp_path / 'journal.db'
    _ = NewReservationExecutor(SaveIntentJournal(path), ResumableSurface(stop_after_prepare=True)).run(intent(), dry_run=False)
    surface = ResumableSurface()
    # When: a fresh executor reconciles the exact prepared editor.
    result = NewReservationExecutor(SaveIntentJournal(path), surface).resume(intent(), dry_run=False)
    # Then: no preparation/upload repeats, and only one save occurs.
    assert result.execution.state is ExecutionState.VERIFIED
    assert 'prepare' not in surface.calls and surface.calls.count('save') == 1


@pytest.mark.parametrize('failure', ['input', 'save'])
def test_interrupted_external_action_never_repeats(tmp_path: Path, failure: str) -> None:
    # Given: execution died inside input or save.
    path = tmp_path / 'journal.db'
    surface = ResumableSurface(interrupt_input=failure == 'input', fail_save=failure == 'save')
    with pytest.raises(TimeoutError):
        _ = NewReservationExecutor(SaveIntentJournal(path), surface).run(intent(), dry_run=False)
    retry = ResumableSurface()
    # When: resume is explicitly requested after restart.
    result = NewReservationExecutor(SaveIntentJournal(path), retry).resume(intent(), dry_run=False)
    # Then: ambiguity holds, never a new upload or save.
    assert result.execution.state is ExecutionState.HELD
    assert 'prepare' not in retry.calls and 'save' not in retry.calls


def test_legacy_claim_is_not_migrated_to_safe(tmp_path: Path) -> None:
    # Given: the old writer left a claim with no durable action boundary.
    journal = SaveIntentJournal(tmp_path / 'journal.db')
    assert journal.claim(DailySlot(intent().scheduled_at).key, intent().package_digest)
    surface = ResumableSurface()
    # When: resume examines that historical claim.
    result = NewReservationExecutor(journal, surface).resume(intent(), dry_run=False)
    # Then: absence of evidence is not proof of no input/save.
    assert result.execution.state is ExecutionState.HELD
    assert 'prepare' not in surface.calls and 'save' not in surface.calls


@pytest.mark.parametrize('failure', ['editor', 'missing_editor', 'inventory', 'authority', 'pause', 'expiry', 'package'])
def test_resume_rechecks_every_boundary(tmp_path: Path, failure: str) -> None:
    # Given: a proven prepared state followed by changed evidence or permission.
    path = tmp_path / 'journal.db'
    _ = NewReservationExecutor(SaveIntentJournal(path), ResumableSurface(stop_after_prepare=True)).run(intent(), dry_run=False)
    retry = ResumableSurface(
        fingerprint=None if failure == 'missing_editor' else 'e' * 64 if failure == 'editor' else 'd' * 64,
        prior=frozenset({PostId('91'), PostId('99')}) if failure == 'inventory' else frozenset({PostId('91')}),
        denied=failure == 'authority', calls=['prepare'] if failure in ('pause', 'expiry') else [],
        stop_after_prepare=failure == 'pause', expire_after_prepare=failure == 'expiry')
    request = replace(intent(), package_digest='e' * 64) if failure == 'package' else intent()
    # When: attempting explicit resume.
    result = NewReservationExecutor(SaveIntentJournal(path), retry).resume(request, dry_run=False)
    # Then: changed evidence never reaches save or new preparation.
    assert result.execution.state in (ExecutionState.HELD, ExecutionState.BLOCKED)
    assert 'save' not in retry.calls
    assert retry.calls.count('prepare') == (1 if failure in ('pause', 'expiry') else 0)


def test_concurrent_resume_claims_only_one_save(tmp_path: Path) -> None:
    # Given: separate executors sharing a real SQLite journal and one prepared slot.
    path = tmp_path / 'journal.db'
    _ = NewReservationExecutor(SaveIntentJournal(path), ResumableSurface(stop_after_prepare=True)).run(intent(), dry_run=False)
    surfaces = [ResumableSurface() for _ in range(4)]

    def resume(surface: ResumableSurface) -> ExecutionState:
        return NewReservationExecutor(SaveIntentJournal(path), surface).resume(intent(), dry_run=False).execution.state

    # When: four independent callers contend for the same save boundary.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(resume, surfaces))
    # Then: at least one verifies, but no second save or preparation occurs.
    assert ExecutionState.VERIFIED in results
    assert sum(surface.calls.count('save') for surface in surfaces) == 1
    assert all('prepare' not in surface.calls for surface in surfaces)


def test_resume_default_dry_run_never_touches_surface(tmp_path: Path) -> None:
    # Given: an otherwise ready executor.
    surface = ResumableSurface()
    executor = NewReservationExecutor(SaveIntentJournal(tmp_path / 'journal.db'), surface)
    # When: resume is invoked without explicit execution.
    result = executor.resume(intent())
    # Then: it is inert by default.
    assert result.execution.state is ExecutionState.DRY_RUN and surface.calls == []
