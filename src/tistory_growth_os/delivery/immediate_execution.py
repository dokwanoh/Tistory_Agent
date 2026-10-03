from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
import sqlite3
from typing import Protocol

from ..domain.ids import PostId
from ..domain.publishing_errors import PublishingInvariantError
from .immediate_readback import ImmediateObservation, ImmediateTarget, verify_immediate_publication
from .immediate_media_journal import ImmediateMediaJournal
from .new_reservation_identity import SavedIdentity
from .reservation_execution import ExecutionResult, ExecutionState
from .reservation_readback import ReservationContent
from .save_intents import SaveIntentJournal


@dataclass(frozen=True, slots=True)
class ImmediateIntent:
    operation_id: str
    content: ReservationContent = field(repr=False)
    package_digest: str
    valid_until: datetime

    def __post_init__(self) -> None:
        if (re.fullmatch(r'[a-zA-Z0-9_-]+', self.operation_id) is None
                or re.fullmatch(r'[0-9a-f]{64}', self.package_digest) is None
                or self.valid_until.utcoffset() is None):
            raise PublishingInvariantError('INTENT_INVALID', '/immediate', 'valid operation, digest and deadline required')

    @property
    def key(self) -> str:
        return 'immediate/' + self.operation_id


class ImmediateJournal:
    def __init__(self, path: Path) -> None:
        self.path: Path = path
        self.saves: SaveIntentJournal = SaveIntentJournal(path)
        self.media: ImmediateMediaJournal = ImmediateMediaJournal(path)
        with closing(sqlite3.connect(path)) as connection, connection:
            _ = connection.execute('''CREATE TABLE IF NOT EXISTS immediate_attempts (
                operation_key TEXT PRIMARY KEY NOT NULL, digest TEXT NOT NULL,
                started_at TEXT NOT NULL)''')

    def start(self, request: ImmediateIntent, now: datetime) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            _ = connection.execute('PRAGMA synchronous = FULL')
            _ = connection.execute('INSERT INTO immediate_attempts VALUES (?, ?, ?)',
                                   (request.key, request.package_digest, now.isoformat()))

    def started_at(self, request: ImmediateIntent) -> datetime | None:
        values: list[str] = []

        def decode(value: bytes) -> str:
            result = value.decode('utf-8')
            values.append(result)
            return result

        with closing(sqlite3.connect(self.path)) as connection:
            connection.text_factory = decode
            _ = connection.execute('''SELECT started_at FROM immediate_attempts
                WHERE operation_key = ? AND digest = ? AND typeof(started_at) = 'text' ''',
                (request.key, request.package_digest)).fetchall()
        return datetime.fromisoformat(values[0]) if len(values) == 1 else None

    def can_resume_editor(self, request: ImmediateIntent) -> bool:
        values: list[str] = []

        def decode(value: bytes) -> str:
            result = value.decode('utf-8')
            values.append(result)
            return result

        with closing(sqlite3.connect(self.path)) as connection:
            connection.text_factory = decode
            _ = connection.execute('''SELECT slot_key FROM save_intents WHERE slot_key=? AND package_digest=?
                AND NOT EXISTS(SELECT 1 FROM immediate_attempts WHERE operation_key=?)
                AND NOT EXISTS(SELECT 1 FROM save_receipts WHERE slot_key=?)''',
                (request.key, request.package_digest, request.key, request.key)).fetchall()
        return values == [request.key]


class ImmediateSurface(Protocol):
    def now(self) -> datetime: ...
    def stopped(self) -> bool: ...
    def authorize(self, request: ImmediateIntent, now: datetime) -> tuple[str, ...]: ...
    def inventory(self) -> frozenset[PostId] | None: ...
    def prepare(self, request: ImmediateIntent) -> None: ...
    def save(self, request: ImmediateIntent) -> SavedIdentity | None: ...
    def readback(self, target: ImmediateTarget) -> ImmediateObservation | None: ...


@dataclass(frozen=True, slots=True)
class ImmediateResult:
    execution: ExecutionResult
    target: ImmediateTarget | None = None


@dataclass(frozen=True, slots=True)
class ImmediateExecutor:
    journal: ImmediateJournal
    surface: ImmediateSurface

    def _gate(self, request: ImmediateIntent) -> tuple[str, ...]:
        def boundaries() -> tuple[str, ...]:
            now = self.surface.now()
            if self.surface.stopped():
                return ('kill_switch',)
            if now.utcoffset() is None or now >= request.valid_until:
                return ('expired_or_invalid_clock',)
            return ()
        return boundaries() or self.surface.authorize(request, self.surface.now()) or boundaries()

    def run(self, request: ImmediateIntent, *, dry_run: bool = True, resume_editor: bool = False) -> ImmediateResult:
        if dry_run:
            return ImmediateResult(ExecutionResult(ExecutionState.DRY_RUN))
        reasons = self._gate(request)
        if reasons:
            return ImmediateResult(ExecutionResult(ExecutionState.BLOCKED, reasons))
        permitted = (self.journal.can_resume_editor(request) if resume_editor
                     else self.journal.saves.claim(request.key, request.package_digest))
        if not permitted:
            return ImmediateResult(ExecutionResult(ExecutionState.HELD, ('existing_intent',)))
        before = self.surface.inventory()
        if before is None:
            return ImmediateResult(ExecutionResult(ExecutionState.BLOCKED, ('incomplete_inventory',)))
        self.surface.prepare(request)
        reasons = self._gate(request)
        if reasons:
            return ImmediateResult(ExecutionResult(ExecutionState.BLOCKED, reasons))
        started = self.surface.now()
        self.journal.start(request, started)
        saved = self.surface.save(request)
        if saved is None:
            return ImmediateResult(ExecutionResult(ExecutionState.UNKNOWN, ('missing_identity',)))
        if saved.post_id in before:
            return ImmediateResult(ExecutionResult(ExecutionState.MISMATCH, ('preexisting_identity',)))
        self.journal.saves.record_receipt(request.key, request.package_digest, saved)
        return self._verify(ImmediateTarget(saved, request.content, started), request.valid_until)

    def recover(self, request: ImmediateIntent) -> ImmediateResult:
        if self.surface.stopped():
            return ImmediateResult(ExecutionResult(ExecutionState.BLOCKED, ('kill_switch',)))
        saved = self.journal.saves.receipt(request.key, request.package_digest)
        started = self.journal.started_at(request)
        if saved is None or started is None:
            return ImmediateResult(ExecutionResult(ExecutionState.HELD, ('missing_receipt',)))
        return self._verify(ImmediateTarget(saved, request.content, started), request.valid_until)

    def _verify(self, target: ImmediateTarget, valid_until: datetime) -> ImmediateResult:
        observation = self.surface.readback(target)
        if observation is not None and observation.published_at.utcoffset() is not None and observation.published_at >= valid_until:
            return ImmediateResult(ExecutionResult(ExecutionState.MISMATCH, ('publication_expired',)), target)
        check = verify_immediate_publication(target, observation, self.surface.now())
        return ImmediateResult(ExecutionResult(ExecutionState(check.status.value), check.mismatches), target)
