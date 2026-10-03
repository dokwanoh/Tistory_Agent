from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from typing import Protocol, assert_never

from ..domain.ids import PostId
from ..domain.publishing_future import VerificationStatus
from .new_reservation_identity import NewReservationIntent, SavedIdentity, bind_new_reservation
from .reservation_execution import ExecutionResult, ExecutionState
from .reservation_readback import (
    DailySlot, ReservationObservation, ReservationTarget, verify_reservation,
)
from .save_intents import SaveIntentJournal
from .resume_journal import ResumePoint, ResumeStage


class NewReservationSurface(Protocol):
    def now(self) -> datetime: ...
    def stopped(self) -> bool: ...
    def authorize(self, request: NewReservationIntent, now: datetime) -> tuple[str, ...]: ...
    def inventory(self) -> frozenset[PostId] | None: ...
    def prepare(self, request: NewReservationIntent) -> None: ...
    def save(self, request: NewReservationIntent) -> SavedIdentity | None: ...
    def readback(self, target: ReservationTarget) -> ReservationObservation | None: ...
    def preparation_fingerprint(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class NewReservationResult:
    execution: ExecutionResult
    target: ReservationTarget | None = None


@dataclass(frozen=True, slots=True)
class NewReservationExecutor:
    journal: SaveIntentJournal
    surface: NewReservationSurface

    def run(self, request: NewReservationIntent, *, dry_run: bool = True) -> NewReservationResult:
        if dry_run:
            return NewReservationResult(ExecutionResult(ExecutionState.DRY_RUN))
        reasons = self._gate(request)
        if reasons:
            return NewReservationResult(ExecutionResult(ExecutionState.BLOCKED, reasons))
        slot = DailySlot(request.scheduled_at)
        if not self.journal.claim(slot.key, request.package_digest, recoverable=True):
            return NewReservationResult(ExecutionResult(ExecutionState.HELD, ("existing_intent",)))
        return self._continue(request, ResumePoint(slot.key, request.package_digest, ResumeStage.BEFORE_INPUT))

    def resume(self, request: NewReservationIntent, *, dry_run: bool = True) -> NewReservationResult:
        if dry_run:
            return NewReservationResult(ExecutionResult(ExecutionState.DRY_RUN))
        reasons = self._gate(request)
        if reasons:
            return NewReservationResult(ExecutionResult(ExecutionState.BLOCKED, reasons))
        slot = DailySlot(request.scheduled_at)
        if self.journal.receipt(slot.key, request.package_digest) is not None:
            return self.recover(request)
        point = self.journal.recovery.read(slot.key, request.package_digest)
        if point is None:
            return NewReservationResult(ExecutionResult(ExecutionState.HELD, ('missing_resume_evidence',)))
        match point.stage:
            case ResumeStage.BEFORE_INPUT | ResumeStage.PREPARED:
                return self._continue(request, point)
            case ResumeStage.INPUT_STARTED | ResumeStage.SAVE_STARTED:
                return NewReservationResult(ExecutionResult(ExecutionState.HELD, (point.stage.value,)))
            case _:
                assert_never(point.stage)

    def _continue(self, request: NewReservationIntent, point: ResumePoint) -> NewReservationResult:
        prior = self.surface.inventory()
        if prior is None:
            return NewReservationResult(ExecutionResult(ExecutionState.BLOCKED, ("inventory_required",)))
        inventory_digest = sha256('\n'.join(sorted(prior)).encode()).hexdigest()
        if point.inventory_digest and point.inventory_digest != inventory_digest:
            return NewReservationResult(ExecutionResult(ExecutionState.HELD, ('inventory_changed',)))
        reasons = self._gate(request)
        if reasons:
            return NewReservationResult(ExecutionResult(ExecutionState.BLOCKED, reasons))
        ready = point
        match point.stage:
            case ResumeStage.BEFORE_INPUT:
                started = replace(point, stage=ResumeStage.INPUT_STARTED, inventory_digest=inventory_digest)
                if not self.journal.recovery.advance(point, started):
                    return NewReservationResult(ExecutionResult(ExecutionState.HELD, ('concurrent_transition',)))
                self.surface.prepare(request)
                fingerprint = self.surface.preparation_fingerprint()
                if fingerprint is None:
                    return NewReservationResult(ExecutionResult(ExecutionState.HELD, ('preparation_unverified',)))
                ready = replace(started, stage=ResumeStage.PREPARED, editor_digest=fingerprint)
                if not self.journal.recovery.advance(started, ready):
                    return NewReservationResult(ExecutionResult(ExecutionState.HELD, ('concurrent_transition',)))
            case ResumeStage.PREPARED:
                if self.surface.preparation_fingerprint() != point.editor_digest:
                    return NewReservationResult(ExecutionResult(ExecutionState.HELD, ('prepared_editor_changed',)))
            case ResumeStage.INPUT_STARTED | ResumeStage.SAVE_STARTED:
                return NewReservationResult(ExecutionResult(ExecutionState.HELD, ('unsafe_stage',)))
            case _:
                assert_never(point.stage)
        reasons = self._gate(request)
        if reasons:
            return NewReservationResult(ExecutionResult(ExecutionState.BLOCKED, reasons))
        if not self.journal.recovery.advance(ready, replace(ready, stage=ResumeStage.SAVE_STARTED)):
            return NewReservationResult(ExecutionResult(ExecutionState.HELD, ('concurrent_transition',)))
        saved = self.surface.save(request)
        if saved is None:
            return NewReservationResult(ExecutionResult(ExecutionState.UNKNOWN, ("missing_save_identity",)))
        if saved.post_id in prior:
            return NewReservationResult(ExecutionResult(ExecutionState.MISMATCH, ("identity_preexisting",)))
        target = bind_new_reservation(request, saved, prior)
        self.journal.record_receipt(point.slot_key, request.package_digest, saved)
        return self._verify(target)

    def recover(self, request: NewReservationIntent) -> NewReservationResult:
        saved = self.journal.receipt(DailySlot(request.scheduled_at).key, request.package_digest)
        if saved is None:
            return NewReservationResult(ExecutionResult(ExecutionState.UNKNOWN, ("missing_save_identity",)))
        target = ReservationTarget(saved.post_id, saved.url, request.scheduled_at, request.content)
        if self.surface.stopped():
            return NewReservationResult(ExecutionResult(ExecutionState.BLOCKED, ("kill_switch",)), target)
        return self._verify(target)

    def _verify(self, target: ReservationTarget) -> NewReservationResult:
        observation = self.surface.readback(target)
        check = verify_reservation(target, observation, self.surface.now())
        match check.status:
            case VerificationStatus.VERIFIED:
                execution = ExecutionResult(ExecutionState.VERIFIED)
            case VerificationStatus.MISMATCH:
                execution = ExecutionResult(ExecutionState.MISMATCH, check.mismatches)
            case VerificationStatus.UNKNOWN:
                execution = ExecutionResult(ExecutionState.UNKNOWN, check.mismatches)
            case _:
                assert_never(check.status)
        return NewReservationResult(execution, target)

    def _gate(self, request: NewReservationIntent) -> tuple[str, ...]:
        now = self.surface.now()
        reasons = self._stop_reasons(request, now)
        if reasons:
            return reasons
        reasons = self.surface.authorize(request, now)
        return reasons or self._stop_reasons(request, self.surface.now())

    def _stop_reasons(self, request: NewReservationIntent, now: datetime) -> tuple[str, ...]:
        if self.surface.stopped():
            return ("kill_switch",)
        if now.utcoffset() is None:
            return ("timezone_required",)
        if now >= request.scheduled_at:
            return ("slot_expired",)
        return ()
