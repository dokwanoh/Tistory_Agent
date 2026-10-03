from contextlib import closing
import json
from pathlib import Path
import sqlite3

from ..contracts.json_decode import parse_json
from ..domain.common import Fields, array, identifier
from ..domain.ids import MediaId
from ..domain.publishing_errors import PublishingInvariantError
from .immediate_media import MediaBinding


class ImmediateMediaJournal:
    def __init__(self, path: Path) -> None:
        self.path: Path = path
        with closing(sqlite3.connect(path)) as connection, connection:
            _ = connection.execute('''CREATE TABLE IF NOT EXISTS immediate_media (
                operation_key TEXT PRIMARY KEY NOT NULL, digest TEXT NOT NULL, bindings TEXT NOT NULL)''')

    def record(self, key: str, digest: str, bindings: tuple[MediaBinding, ...]) -> None:
        if len(bindings) != 4 or len({item.asset_id for item in bindings}) != 4:
            raise PublishingInvariantError('MEDIA_INVALID', '/bindings', 'four distinct media required')
        payload = json.dumps({'media': [{'asset_id': item.asset_id, 'filename': item.filename,
                                        'source_sha256': item.source_sha256} for item in bindings]})
        with closing(sqlite3.connect(self.path)) as connection, connection:
            _ = connection.execute('PRAGMA synchronous = FULL')
            cursor = connection.execute('''INSERT INTO immediate_media
                SELECT slot_key, package_digest, ? FROM save_intents WHERE slot_key = ? AND package_digest = ?
                AND NOT EXISTS(SELECT 1 FROM immediate_attempts WHERE operation_key = ?)
                ON CONFLICT(operation_key) DO UPDATE SET operation_key = excluded.operation_key
                WHERE immediate_media.digest = excluded.digest AND immediate_media.bindings = excluded.bindings''',
                (payload, key, digest, key))
            if cursor.rowcount != 1:
                raise PublishingInvariantError('MEDIA_CONFLICT', '/bindings', 'matching pre-save claim and immutable bindings required')

    def read(self, key: str, digest: str) -> tuple[MediaBinding, ...]:
        values: list[str] = []

        def decode(value: bytes) -> str:
            result = value.decode('utf-8')
            values.append(result)
            return result

        with closing(sqlite3.connect(self.path)) as connection:
            connection.text_factory = decode
            _ = connection.execute('''SELECT bindings FROM immediate_media WHERE operation_key = ? AND digest = ?
                AND typeof(bindings) = 'text' ''', (key, digest)).fetchall()
        if not values:
            return ()
        if len(values) != 1:
            raise PublishingInvariantError('MEDIA_INVALID', '/bindings', 'one receipt required')
        fields = Fields.parse(parse_json(values[0]), '', ('media',))
        bindings: list[MediaBinding] = []
        for index, value in enumerate(array(fields, 'media', True)):
            entry = Fields.parse(value, f'/media/{index}', ('asset_id', 'filename', 'source_sha256'))
            bindings.append(MediaBinding(MediaId(identifier(entry, 'asset_id', r'[a-zA-Z0-9_-]+')),
                identifier(entry, 'filename', r'[a-zA-Z0-9_-]+\.(?:jpg|jpeg|png|webp)'),
                identifier(entry, 'source_sha256', r'[0-9a-f]{64}')))
        if len(bindings) != 4 or len({item.asset_id for item in bindings}) != 4:
            raise PublishingInvariantError('MEDIA_INVALID', '/bindings', 'four distinct receipts required')
        return tuple(bindings)
