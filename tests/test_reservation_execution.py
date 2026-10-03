from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tistory_growth_os.delivery.reservation_execution import (
    ReservationAttempt, ReservationExecutor, ExecutionState,
)
from tistory_growth_os.delivery.reservation_readback import (
    ReservationContent, ReservationMedia, ReservationTarget,
    ReservationObservation, SavedVisibility, DailySlot,
)
from tistory_growth_os.delivery.save_intents import SaveIntentJournal
from tistory_growth_os.domain.ids import MediaId, PostId


def attempt() -> ReservationAttempt:
    media = tuple(ReservationMedia(MediaId(str(n)), f"그림 {n}") for n in range(4))
    content = ReservationContent("예약 연습", "a" * 64, media, MediaId("0"), None, "생활정보", ())
    target = ReservationTarget(PostId("fixture"), "https://example.tistory.com/entry/fixture",
                               datetime.fromisoformat("2030-01-01T12:00:00+09:00"), content)
    return ReservationAttempt(target, "b" * 64)


@dataclass(frozen=True, slots=True)
class Surface:
    calls: list[str] = field(default_factory=list)
    times: list[datetime] = field(default_factory=lambda: [attempt().target.scheduled_at - timedelta(hours=1)])
    stops: list[bool] = field(default_factory=lambda: [False])
    issues: tuple[str, ...] = ()
    missing_readback: bool = False
    corrupt_title: bool = False
    fail_save: bool = False
    fail_prepare: bool = False

    def now(self) -> datetime:
        return self.times.pop(0) if len(self.times) > 1 else self.times[0]

    def stopped(self) -> bool:
        return self.stops.pop(0) if len(self.stops) > 1 else self.stops[0]

    def authorize(self, request: ReservationAttempt, now: datetime) -> tuple[str, ...]:
        self.calls.append("authorize")
        return self.issues

    def prepare(self, request: ReservationAttempt) -> None:
        self.calls.append("prepare")
        if self.fail_prepare:
            raise TimeoutError()

    def save(self, request: ReservationAttempt) -> None:
        self.calls.append("save")
        if self.fail_save:
            raise TimeoutError()

    def readback(self, request: ReservationAttempt) -> ReservationObservation | None:
        self.calls.append("readback")
        if self.missing_readback:
            return None
        target = request.target
        if self.corrupt_title:
            target = replace(target, content=replace(target.content, title="다른 제목"))
        return ReservationObservation(target, SavedVisibility.SCHEDULED, self.now())


def test_dry_run_never_calls_surface_or_consumes_claim(tmp_path: Path) -> None:
    # Given a valid request and fresh journal; When dry-run executes; Then no surface calls.
    surface = Surface()
    journal = SaveIntentJournal(tmp_path / "intents.db")
    result = ReservationExecutor(journal, surface).run(attempt())
    assert result.state is ExecutionState.DRY_RUN
    assert surface.calls == []
    assert journal.claim(DailySlot(attempt().target.scheduled_at).key, attempt().package_digest)


def test_authorization_denial_prevents_preparation(tmp_path: Path) -> None:
    surface = Surface(issues=("review_expired",))
    result = ReservationExecutor(SaveIntentJournal(tmp_path / "intents.db"), surface).run(attempt(), dry_run=False)
    assert result.state is ExecutionState.BLOCKED
    assert result.reasons == ("review_expired",)
    assert surface.calls == ["authorize"]


def test_success_requires_readback_and_retry_never_writes(tmp_path: Path) -> None:
    surface = Surface()
    path = tmp_path / "intents.db"
    result = ReservationExecutor(SaveIntentJournal(path), surface).run(attempt(), dry_run=False)
    assert result.state is ExecutionState.VERIFIED
    assert surface.calls == ["authorize", "prepare", "authorize", "save", "readback"]
    replay = Surface()
    assert ReservationExecutor(SaveIntentJournal(path), replay).run(attempt(), dry_run=False).state is ExecutionState.HELD
    assert replay.calls == ["authorize"]


@pytest.mark.parametrize("surface,expected", [(Surface(missing_readback=True), ExecutionState.UNKNOWN),
                                             (Surface(corrupt_title=True), ExecutionState.MISMATCH)])
def test_unverified_save_keeps_durable_hold(tmp_path: Path, surface: Surface, expected: ExecutionState) -> None:
    journal = SaveIntentJournal(tmp_path / "intents.db")
    result = ReservationExecutor(journal, surface).run(attempt(), dry_run=False)
    assert result.state is expected
    assert not journal.claim(DailySlot(attempt().target.scheduled_at).key, "c" * 64)


def test_save_exception_propagates_without_unlocking_retry(tmp_path: Path) -> None:
    surface = Surface(fail_save=True)
    journal = SaveIntentJournal(tmp_path / "intents.db")
    with pytest.raises(TimeoutError):
        ReservationExecutor(journal, surface).run(attempt(), dry_run=False)
    assert surface.calls[-1] == "save"
    assert not journal.claim(DailySlot(attempt().target.scheduled_at).key, attempt().package_digest)


@pytest.mark.parametrize("after_prepare", [False, True])
def test_kill_switch_stops_before_next_write(tmp_path: Path, after_prepare: bool) -> None:
    surface = Surface(stops=[False, False, True] if after_prepare else [True])
    result = ReservationExecutor(SaveIntentJournal(tmp_path / "intents.db"), surface).run(attempt(), dry_run=False)
    assert result.state is ExecutionState.BLOCKED
    assert "save" not in surface.calls
    assert ("prepare" in surface.calls) is after_prepare


@pytest.mark.parametrize("after_prepare", [False, True])
def test_expired_slot_stops_before_next_write(tmp_path: Path, after_prepare: bool) -> None:
    deadline = attempt().target.scheduled_at
    early = deadline - timedelta(minutes=1)
    surface = Surface(times=[early, early, deadline] if after_prepare else [deadline])
    result = ReservationExecutor(SaveIntentJournal(tmp_path / "intents.db"), surface).run(attempt(), dry_run=False)
    assert result.state is ExecutionState.BLOCKED
    assert "save" not in surface.calls
    assert ("prepare" in surface.calls) is after_prepare


def test_deadline_crossed_during_authorization_never_prepares(tmp_path: Path) -> None:
    deadline = attempt().target.scheduled_at
    surface = Surface(times=[deadline - timedelta(seconds=1), deadline])
    result = ReservationExecutor(SaveIntentJournal(tmp_path / "intents.db"), surface).run(attempt(), dry_run=False)
    assert result.state is ExecutionState.BLOCKED
    assert "prepare" not in surface.calls


def test_preparation_failure_already_has_durable_hold(tmp_path: Path) -> None:
    journal = SaveIntentJournal(tmp_path / "intents.db")
    with pytest.raises(TimeoutError):
        ReservationExecutor(journal, Surface(fail_prepare=True)).run(attempt(), dry_run=False)
    assert not journal.claim(DailySlot(attempt().target.scheduled_at).key, attempt().package_digest)
