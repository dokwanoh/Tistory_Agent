from dataclasses import asdict
from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re

from ..contracts.json_ast import JsonArray, JsonMember, JsonObject, JsonString
from ..contracts.json_decode import parse_json
from ..contracts.json_encode import encode_json
from ..domain.common import Fields, array, as_object, text
from ..research.intake import public_source_url
from .contracts import PreparationError
from .shared_sources import SourceDocument, SourceReader, document_from_value
from .source_pool import read_pool


def operation_root(directory: Path) -> Path:
    roots = tuple(parent for parent in (directory, *directory.parents) if (parent / 'input.json').is_file())
    return roots[-1] if roots else directory


def urls_in(source: str) -> tuple[str, ...]:
    normalized = source.replace('\\"', '"').replace('\\/', '/')
    values = (unescape(match.group()).rstrip('.,;)') for match in re.finditer(r"https://[^\s<>\"'\\]+", normalized))
    return tuple(dict.fromkeys(value for value in values if public_source_url(value)))


def seed_pool(reader: SourceReader, root: Path) -> None:
    initial = root / 'input.json'
    if not initial.is_file():
        return
    fields = Fields(as_object(parse_json(initial.read_text()), ''), '', ())
    if fields.value.get('source_pool_sha256') is None:
        return
    pool = Fields(as_object(parse_json(read_pool(root, text(fields, 'source_pool_sha256'))), ''), '', ())
    for raw in array(pool, 'documents', True):
        item = Fields(as_object(raw, ''), '', ())
        url = text(item, 'url')
        document = SourceDocument(url, text(item, 'checked_at'), 'full_text', text(item, 'body'),
            text(item, 'body_sha256'), text(item, 'response_sha256'), urls_in(encode_json(item.required('links'))),
            text(item, 'published_at'), text(item, 'title'))
        reader.remember(document)


def collect_context(directory: Path, prompt: str, urls: tuple[str, ...]) -> str:
    root = operation_root(directory)
    reader = SourceReader(root / 'shared-sources')
    seed_pool(reader, root)
    requested = tuple(dict.fromkeys(urls or urls_in(prompt)))
    documents: list[SourceDocument] = []
    uncollected: list[str] = []
    used = 0
    for index, url in enumerate(requested):
        if index >= 24:
            uncollected.append(url)
            continue
        document = reader.read(url)
        size = len(json.dumps(asdict(document), ensure_ascii=False).encode())
        if used + size > 900_000:
            uncollected.append(url)
            continue
        used += size
        documents.append(document)
    return json.dumps({'documents': [asdict(doc) for doc in documents],
        'uncollected_urls': uncollected}, ensure_ascii=False)


def bind_detail_sources(raw: str, snapshots: str) -> str:
    source = Fields(as_object(parse_json(snapshots), ''), '', ())
    documents = {text(Fields(as_object(item, ''), '', ()), 'url'): document_from_value(item)
                 for item in array(source, 'documents', False)}
    fields = Fields(as_object(parse_json(raw), ''), '', ())
    updated: list[JsonObject] = []
    for item in array(fields, 'sources', True):
        record = Fields(as_object(item, ''), '', ())
        url = text(record, 'url')
        doc = documents.get(url)
        access = doc.access if doc is not None else 'unavailable'
        checked = doc.checked_at if doc is not None else 'UNCOLLECTED'
        updated.append(JsonObject(tuple(JsonMember(member.key,
            JsonString(access) if member.key == 'access' else JsonString(checked)
            if member.key == 'checked_at' else member.value) for member in record.value.members)))
    return encode_json(JsonObject(tuple(JsonMember(member.key,
        JsonArray(tuple(updated)) if member.key == 'sources' else member.value) for member in fields.value.members)))


def checked_snapshot(directory: Path, stage: str) -> str:
    path = directory / f'{stage}.sources.json'
    receipt = Fields(as_object(parse_json((directory / f'{stage}.receipt.json').read_text()), ''), '', ())
    if receipt.value.get('sources_sha256') is None:
        if path.exists():
            raise PreparationError('source_snapshot_changed')
        return ''
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise PreparationError('source_snapshot_changed')
    raw = path.read_text()
    if receipt.value.get('sources_sha256') != JsonString(sha256(raw.encode()).hexdigest()):
        raise PreparationError('source_snapshot_changed')
    return raw
