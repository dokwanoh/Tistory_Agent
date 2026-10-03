from dataclasses import replace
from datetime import datetime

from ..contracts.json_ast import JsonArray, JsonMember, JsonObject, JsonString
from ..contracts.json_decode import parse_json
from ..domain.common import Fields, array, as_object, boolean, datetime_value, strings, text
from ..research.intake import public_source_url
from .contracts import Candidate, PreparationError


def enrich_candidate(source: str, candidate: Candidate, checked_at: datetime) -> Candidate:
    fields = Fields.parse(parse_json(source), '', ('candidate_id', 'sources', 'essential_facts'))
    if text(fields, 'candidate_id') != candidate.candidate_id:
        raise PreparationError('evidence_candidate_mismatch')
    sources: list[JsonObject] = []
    primary_urls: set[str] = set()
    urls = set(candidate.urls)
    for raw in array(fields, 'sources', True):
        source_object = as_object(raw, '/sources')
        keys = ('url', 'primary', 'checked_at', 'support')
        if source_object.get('access') is not None:
            keys += ('access',)
        entry = Fields.parse(source_object, '/sources', keys)
        url = text(entry, 'url')
        if source_object.get('access') == JsonString('unavailable') and text(entry, 'checked_at') == 'UNCOLLECTED':
            continue
        recorded = as_object(raw, '/sources')
        if text(entry, 'checked_at') == 'RUNTIME':
            recorded = JsonObject(tuple(JsonMember(member.key,
                JsonString(checked_at.isoformat()) if member.key == 'checked_at' else member.value)
                for member in recorded.members))
        timestamp = datetime_value(Fields(recorded, '', ()), 'checked_at')
        if not public_source_url(url) or not candidate.event_at <= timestamp <= checked_at:
            raise PreparationError('source_url_or_time_invalid')
        _ = text(entry, 'support')
        if boolean(entry, 'primary') and source_object.get('access') == JsonString('full_text'):
            primary_urls.add(url)
        urls.add(url)
        sources.append(recorded)
    topics: list[str] = []
    for raw in array(fields, 'essential_facts', True):
        fact = Fields.parse(raw, '/essential_facts', ('topic', 'status', 'detail', 'source_urls'))
        topics.append(text(fact, 'topic'))
        if text(fact, 'status') not in ('confirmed', 'not_applicable'):
            raise PreparationError('essential_fact_unresolved')
        _ = text(fact, 'detail')
        references = set(strings(fact, 'source_urls', True, r'https://\S+'))
        if not references <= urls or not references & primary_urls:
            raise PreparationError('essential_fact_primary_source_required')
    if sorted(topics) != ['answer', 'conditions', 'timeline']:
        raise PreparationError('essential_fact_coverage_required')
    pack = JsonObject((JsonMember('sources', JsonArray(tuple(sources))),
                       JsonMember('essential_facts', fields.required('essential_facts'))))
    evidence = JsonObject(tuple(member for member in candidate.evidence.members
                                if member.key != 'official_detail') + (JsonMember('official_detail', pack),))
    supported = {text(Fields(as_object(raw, ''), '', ()), 'source_url')
                 for raw in array(Fields(candidate.evidence, '', ()), 'claims', True)}
    for raw in array(fields, 'essential_facts', True):
        supported.update(strings(Fields(as_object(raw, ''), '', ()), 'source_urls', True, r'https://\S+'))
    return replace(candidate, urls=tuple(sorted(supported)), evidence=evidence)
