from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from ..contracts.json_ast import JsonArray, JsonMember, JsonObject
from ..contracts.json_decode import parse_json
from ..domain.common import Fields, array, as_object, boolean, text
from .contracts import Candidate, PreparationError, Research


def read_pool(directory: Path, expected_digest: str) -> str:
    path = directory / 'source-pool.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 500_000:
        raise PreparationError('source_pool_missing')
    source = path.read_text()
    if sha256(source.encode()).hexdigest() != expected_digest:
        raise PreparationError('source_snapshot_changed')
    fields = Fields(as_object(parse_json(source), ''), '', ())
    for raw in array(fields, 'documents', True):
        item = Fields(as_object(raw, ''), '', ())
        if sha256(text(item, 'body').encode()).hexdigest() != text(item, 'body_sha256'):
            raise PreparationError('source_snapshot_changed')
    return source


def bind_sources(research: Research, pool: str) -> Research:
    fields = Fields(as_object(parse_json(pool), ''), '', ())
    documents = {text(Fields(as_object(raw, ''), '', ()), 'url'): raw
                 for raw in array(fields, 'documents', True)}
    candidates: list[Candidate] = []
    for candidate in research.candidates:
        sources = tuple(Fields(as_object(raw, ''), '', ())
                        for raw in array(Fields(candidate.evidence, '', ()), 'sources', True))
        matched = tuple(documents[text(item, 'url')] for item in sources
                        if boolean(item, 'primary') and text(item, 'url') in documents)
        if not matched:
            continue
        evidence = JsonObject(candidate.evidence.members +
            (JsonMember('source_snapshots', JsonArray(matched)),))
        candidates.append(replace(candidate, evidence=evidence))
    if not candidates:
        raise PreparationError('candidate_outside_source_pool')
    return replace(research, candidates=tuple(candidates))
