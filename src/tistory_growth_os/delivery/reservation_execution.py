from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from typing import Protocol, assert_never

from ..domain.publishing_errors import PublishingInvariantError
from ..domain.publishing_future import VerificationStatus
from .reservation_readback import (
    DailySlot, ReservationObservation, ReservationTarget, verify_reservation,
)
from .save_intents import SaveIntentJournal


@dataclass(frozen=True, slots=True)
class ReservationAttempt:
    target: ReservationTarget
    package_digest: str

    def __post_init__(self) -> None:
        _ = DailySlot(self.target.scheduled_at)
        if re.fullmatch(r"[0-9a-f]{64}", self.package_digest) is None:
            raise PublishingInvariantError("DIGEST_INVALID", "/package_digest", "SHA-256 required")


class ExecutionState(StrEnum):
    DRY_RUN = "dry_run"
    BLOCKED = "blocked"
    HELD = "held"
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    state: ExecutionState
    reasons: tuple[str, ...] = ()


class ReservationSurface(Protocol):
    def now(self) -> datetime: ...
    def stopped(self) -> bool: ...
    def authorize(self, request: ReservationAttempt, now: datetime) -> tuple[str, ...]: ...
    def prepare(self, request: ReservationAttempt) -> None: ...
    def save(self, request: ReservationAttempt) -> None: ...
    def readback(self, request: ReservationAttempt) -> ReservationObservation | None: ...


@dataclass(frozen=True, slots=True)
class ReservationExecutor:
    journal: SaveIntentJournal
    surface: ReservationSurface

    def run(self, request: ReservationAttempt, *, dry_run: bool = True) -> ExecutionResult:
        if dry_run:
            return ExecutionResult(ExecutionState.DRY_RUN)
        reasons = self._gate(request)
        if reasons:
            return ExecutionResult(ExecutionState.BLOCKED, reasons)
        slot = DailySlot(request.target.scheduled_at)
        if not self.journal.claim(slot.key, request.package_digest):
            return ExecutionResult(ExecutionState.HELD, ("existing_intent",))
        self.surface.prepare(request)
        reasons = self._gate(request)
        if reasons:
            return ExecutionResult(ExecutionState.BLOCKED, reasons)
        self.surface.save(request)
        observation = self.surface.readback(request)
        check = verify_reservation(request.target, observation, self.surface.now())
        match check.status:
            case VerificationStatus.VERIFIED:
                return ExecutionResult(ExecutionState.VERIFIED)
            case VerificationStatus.MISMATCH:
                return ExecutionResult(ExecutionState.MISMATCH, check.mismatches)
            case VerificationStatus.UNKNOWN:
                return ExecutionResult(ExecutionState.UNKNOWN, check.mismatches)
            case _:
                assert_never(check.status)

    def _gate(self, request: ReservationAttempt) -> tuple[str, ...]:
        now = self.surface.now()
        reasons = self._stop_reasons(request, now)
        if reasons:
            return reasons
        reasons = self.surface.authorize(request, now)
        return reasons or self._stop_reasons(request, self.surface.now())

    def _stop_reasons(self, request: ReservationAttempt, now: datetime) -> tuple[str, ...]:
        if self.surface.stopped():
            return ("kill_switch",)
        if now.utcoffset() is None:
            return ("timezone_required",)
        if now >= request.target.scheduled_at:
            return ("slot_expired",)
        return ()
