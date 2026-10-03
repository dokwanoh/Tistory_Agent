from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re

from ..contracts.json_decode import parse_json
from ..contracts.json_ast import JsonString
from ..domain.common import Fields, array, as_object, text
from .contracts import PreparationError
from .shared_sources import document_from_value


@dataclass(frozen=True, slots=True)
class SourceSpan:
    identity: str
    url: str
    quote: str


@dataclass(frozen=True, slots=True)
class DecisionSpans:
    spans: tuple[SourceSpan, ...]

    @classmethod
    def from_sources(cls, raw: str) -> 'DecisionSpans':
        fields = Fields(as_object(parse_json(raw), ''), '', ())
        spans: list[SourceSpan] = []
        for value in array(fields, 'documents', False):
            document = document_from_value(value)
            if document.access != 'full_text':
                continue
            binding = sha256((document.url + '\n' + document.body_sha256).encode()).hexdigest()
            for match in re.finditer(r'\S[^\r\n]{0,499}', document.body):
                quote = match.group().rstrip()
                if len(quote) >= 4:
                    spans.append(SourceSpan(f'{binding}:{match.start()}', document.url, quote))
        return cls(tuple(spans))

    def schema(self) -> str:
        return json.dumps({'type': 'object', 'additionalProperties': False,
            'required': ['candidate_id', 'angle', 'reason', 'facts'], 'properties': {
                'candidate_id': {'type': 'string'}, 'angle': {'type': 'string'},
                'reason': {'type': 'string'}, 'facts': {'type': 'array', 'items': {
                    'type': 'object', 'additionalProperties': False, 'required': ['claim', 'span_id'],
                    'properties': {'claim': {'type': 'string'}, 'span_id': {'type': 'string',
                        'enum': [span.identity for span in self.spans]}}}}}})

    def prompt(self) -> str:
        return ('\nDECISION OUTPUT CONTRACT: Instead of writing source_url/source_quote, each fact must '
            + 'contain claim and span_id only. Select its exact supporting span from this catalogue. '
            + 'The host copies URL and original quote without rewriting. Split claims across facts if '
            + 'they need separate spans. Do not add words/dates absent from the selected evidence. '
            + 'NONE with facts [] remains available. Semantic judgment is still your responsibility.\n'
            + json.dumps([asdict(span) for span in self.spans], ensure_ascii=False))

    def resolve(self, raw: str) -> str:
        fields = Fields.parse(parse_json(raw), '', ('candidate_id', 'angle', 'reason', 'facts'))
        candidate_id = text(fields, 'candidate_id')
        angle = '' if candidate_id == 'NONE' and fields.required('angle') == JsonString('') else text(fields, 'angle')
        catalogue = {span.identity: span for span in self.spans}
        facts: list[dict[str, str]] = []
        for value in array(fields, 'facts', False):
            fact = Fields.parse(value, '/facts', ('claim', 'span_id'))
            span = catalogue.get(text(fact, 'span_id'))
            if span is None:
                raise PreparationError('decision_span_unknown')
            facts.append({'claim': text(fact, 'claim'), 'source_url': span.url, 'source_quote': span.quote})
        return json.dumps({'candidate_id': candidate_id, 'angle': angle,
            'reason': text(fields, 'reason'), 'facts': facts}, ensure_ascii=False)
