from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3

from ..domain.ids import PostId
from ..domain.publishing_errors import PublishingInvariantError
from .new_reservation_identity import SavedIdentity
from .resume_journal import ResumeJournal


class SaveIntentJournal:
    def __init__(self, path: Path) -> None:
        self._path: Path = path
        self.recovery: ResumeJournal = ResumeJournal(path)
        with closing(sqlite3.connect(path)) as connection, connection:
            _ = connection.execute(
                """CREATE TABLE IF NOT EXISTS save_intents (
                slot_key TEXT PRIMARY KEY NOT NULL,
                package_digest TEXT NOT NULL,
                intent_recorded_at TEXT NOT NULL)"""
            )
            _ = connection.execute(
                """CREATE TABLE IF NOT EXISTS save_receipts (
                slot_key TEXT PRIMARY KEY NOT NULL,
                package_digest TEXT NOT NULL,
                post_id TEXT NOT NULL,
                url TEXT NOT NULL,
                recorded_at TEXT NOT NULL)"""
            )

    def record_receipt(self, slot_key: str, package_digest: str, saved: SavedIdentity) -> None:
        """Persist an observed identity, never permission or proof of saved content."""
        with closing(sqlite3.connect(self._path)) as connection, connection:
            _ = connection.execute("PRAGMA synchronous = FULL")
            cursor = connection.execute(
                """INSERT INTO save_receipts
                SELECT slot_key, package_digest, ?, ?, ? FROM save_intents
                WHERE slot_key = ? AND package_digest = ?
                ON CONFLICT(slot_key) DO UPDATE SET slot_key = excluded.slot_key
                WHERE save_receipts.package_digest = excluded.package_digest
                AND save_receipts.post_id = excluded.post_id AND save_receipts.url = excluded.url""",
                (saved.post_id, saved.url, datetime.now(timezone.utc).isoformat(), slot_key, package_digest),
            )
            if cursor.rowcount != 1:
                raise PublishingInvariantError('RECEIPT_CONFLICT', '/receipt', 'matching claim and immutable identity required')

    def receipt(self, slot_key: str, package_digest: str) -> SavedIdentity | None:
        """Decode selected TEXT columns without propagating untyped SQLite rows."""
        fields: list[str] = []

        def decode_text(value: bytes) -> str:
            text = value.decode('utf-8')
            fields.append(text)
            return text

        with closing(sqlite3.connect(self._path)) as connection:
            connection.text_factory = decode_text
            _ = connection.execute(
                """SELECT r.post_id, r.url FROM save_receipts r
                JOIN save_intents i ON i.slot_key = r.slot_key AND i.package_digest = r.package_digest
                WHERE r.slot_key = ? AND r.package_digest = ?
                AND typeof(r.post_id) = 'text' AND typeof(r.url) = 'text'""",
                (slot_key, package_digest),
            ).fetchall()
        if not fields:
            return None
        if len(fields) != 2:
            raise PublishingInvariantError('RECEIPT_INVALID', '/receipt', 'one identity required')
        return SavedIdentity(PostId(fields[0]), fields[1])

    def claim(self, slot_key: str, package_digest: str, *, recoverable: bool = False) -> bool:
        if not slot_key or slot_key != slot_key.strip():
            raise ValueError("slot_key must be nonempty without outer whitespace")
        if re.fullmatch(r"[0-9a-f]{64}", package_digest) is None:
            raise ValueError("package_digest must be a lowercase SHA-256 digest")
        with closing(sqlite3.connect(self._path)) as connection, connection:
            _ = connection.execute("PRAGMA synchronous = FULL")
            cursor = connection.execute(
                """INSERT INTO save_intents
                (slot_key, package_digest, intent_recorded_at) VALUES (?, ?, ?)
                ON CONFLICT(slot_key) DO NOTHING""",
                (slot_key, package_digest, datetime.now(timezone.utc).isoformat()),
            )
            claimed = cursor.rowcount == 1
            if claimed and recoverable:
                _ = connection.execute('''INSERT INTO resume_points(slot_key,package_digest,stage)
                    VALUES(?,?,'before_input')''', (slot_key, package_digest))
                _ = connection.execute('''INSERT INTO resume_events(slot_key,package_digest,stage)
                    VALUES(?,?,'before_input')''', (slot_key, package_digest))
        return claimed
