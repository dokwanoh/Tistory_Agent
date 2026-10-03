from dataclasses import dataclass
from hashlib import sha256

from ..contracts.json_ast import JsonArray, JsonMember, JsonObject
from ..contracts.json_decode import parse_json
from ..contracts.json_encode import encode_json
from ..domain.common import Fields, array, as_object, boolean, strings, text
from .contracts import PreparationError


@dataclass(frozen=True, slots=True)
class ReviewContext:
    excluded_sessions: frozenset[str]
    previous_payload: str = ''
    previous_review: str = ''


def reusable_blocks(context: ReviewContext, payload: str) -> tuple[JsonObject, ...]:
    if not context.previous_payload or not context.previous_review:
        return ()
    previous = Fields(as_object(parse_json(context.previous_payload), ''), '', ())
    current = Fields(as_object(parse_json(payload), ''), '', ())
    review = Fields(as_object(parse_json(context.previous_review), ''), '', ())
    if text(review, 'subject_sha256') != sha256(context.previous_payload.encode()).hexdigest():
        raise PreparationError('text_review_subject_mismatch')
    if previous.required('candidate_evidence') != current.required('candidate_evidence'):
        return ()
    scope = Fields(as_object(review.required('repair'), ''), '', ())
    affected = set(strings(scope, 'block_ids', False, r'[\w/-]+'))
    if not boolean(review, 'approved') and not affected:
        return ()
    before = {text(Fields(as_object(row, ''), '', ()), 'identity'): row
              for row in array(previous, 'blocks', True)}
    after = {text(Fields(as_object(row, ''), '', ()), 'identity'): row
             for row in array(current, 'blocks', True)}
    records: list[JsonObject] = []
    seen: set[str] = set()
    for raw in array(review, 'blocks', False):
        record = as_object(raw, '')
        identity = text(Fields(record, '', ()), 'identity')
        if identity in seen:
            raise PreparationError('text_review_block_coverage')
        seen.add(identity)
        if identity not in affected and identity in before and before[identity] == after.get(identity):
            records.append(record)
    return tuple(records)


def merge_review(response: str, reused: tuple[JsonObject, ...]) -> str:
    if not reused:
        return response
    fields = Fields(as_object(parse_json(response), ''), '', ())
    rows = array(fields, 'blocks', False)
    returned = {text(Fields(as_object(row, ''), '', ()), 'identity') for row in rows}
    inherited = tuple(row for row in reused if text(Fields(row, '', ()), 'identity') not in returned)
    return encode_json(JsonObject(tuple(JsonMember(member.key,
        JsonArray(tuple(rows) + inherited) if member.key == 'blocks' else member.value)
        for member in fields.value.members)))
