from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re
import sqlite3

from ..domain.publishing_errors import PublishingInvariantError


class ResumeStage(StrEnum):
    BEFORE_INPUT = 'before_input'
    INPUT_STARTED = 'input_started'
    PREPARED = 'prepared'
    SAVE_STARTED = 'save_started'


@dataclass(frozen=True, slots=True)
class ResumePoint:
    slot_key: str
    package_digest: str
    stage: ResumeStage
    inventory_digest: str = ''
    editor_digest: str = ''


class ResumeJournal:
    def __init__(self, path: Path) -> None:
        self.path: Path = path
        with closing(sqlite3.connect(path)) as connection, connection:
            _ = connection.execute('''CREATE TABLE IF NOT EXISTS resume_points (
                slot_key TEXT PRIMARY KEY, package_digest TEXT NOT NULL,
                stage TEXT NOT NULL, inventory_digest TEXT NOT NULL DEFAULT '',
                editor_digest TEXT NOT NULL DEFAULT '')''')
            _ = connection.execute('''CREATE TABLE IF NOT EXISTS resume_events (
                slot_key TEXT NOT NULL, package_digest TEXT NOT NULL, stage TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

    def read(self, slot_key: str, package_digest: str) -> ResumePoint | None:
        values: list[str] = []

        def decode(value: bytes) -> str:
            result = value.decode('utf-8')
            values.append(result)
            return result

        with closing(sqlite3.connect(self.path)) as connection:
            connection.text_factory = decode
            _ = connection.execute('''SELECT r.stage, r.inventory_digest, r.editor_digest
                FROM resume_points r JOIN save_intents i USING(slot_key, package_digest)
                WHERE r.slot_key=? AND r.package_digest=?''', (slot_key, package_digest)).fetchall()
        if not values:
            return None
        if len(values) != 3 or any(value and re.fullmatch('[0-9a-f]{64}', value) is None for value in values[1:]):
            raise PublishingInvariantError('RESUME_INVALID', '/resume', 'invalid durable evidence')
        return ResumePoint(slot_key, package_digest, ResumeStage(values[0]), values[1], values[2])

    def advance(self, before: ResumePoint, after: ResumePoint) -> bool:
        permitted = {(ResumeStage.BEFORE_INPUT, ResumeStage.INPUT_STARTED),
                     (ResumeStage.INPUT_STARTED, ResumeStage.PREPARED),
                     (ResumeStage.PREPARED, ResumeStage.SAVE_STARTED)}
        if ((before.slot_key, before.package_digest) != (after.slot_key, after.package_digest)
                or (before.stage, after.stage) not in permitted
                or re.fullmatch('[0-9a-f]{64}', after.inventory_digest) is None
                or (after.stage in (ResumeStage.PREPARED, ResumeStage.SAVE_STARTED)
                    and re.fullmatch('[0-9a-f]{64}', after.editor_digest) is None)):
            raise PublishingInvariantError('RESUME_TRANSITION', '/resume', 'invalid transition')
        with closing(sqlite3.connect(self.path)) as connection, connection:
            _ = connection.execute('PRAGMA synchronous = FULL')
            cursor = connection.execute('''UPDATE resume_points SET stage=?, inventory_digest=?, editor_digest=?
                WHERE slot_key=? AND package_digest=? AND stage=? AND inventory_digest=? AND editor_digest=?
                AND NOT EXISTS (SELECT 1 FROM save_receipts WHERE slot_key=?)''',
                (after.stage, after.inventory_digest, after.editor_digest, before.slot_key,
                 before.package_digest, before.stage, before.inventory_digest, before.editor_digest, before.slot_key))
            changed = cursor.rowcount == 1
            if changed:
                _ = connection.execute('INSERT INTO resume_events(slot_key,package_digest,stage) VALUES(?,?,?)',
                                       (after.slot_key, after.package_digest, after.stage))
        return changed
