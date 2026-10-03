from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
from typing import Final, assert_never

from tistory_growth_os.contracts.json_decode import parse_json
from tistory_growth_os.domain.common import Fields, text
from tistory_growth_os.preparation.contracts import CHECKS
from tistory_growth_os.preparation.provider import StageRequest, StageResponse


NOW: Final = datetime(2026, 9, 21, 1, tzinfo=timezone.utc)


def research_response() -> str:
    return json.dumps({'candidates': [{'id': f'candidate-{n}', 'title': f'공공과학 행사 {n}',
        'event_at': (NOW - timedelta(hours=1)).isoformat(),
        'event_time_basis': '공식 발표 시각과 별도 보도의 발표 시각을 비교하여 기록했습니다.',
        'reader_question': '이번 공공과학 행사를 이용하기 전에 어떤 조건을 알아두면 좋을까요?',
        'rationale': '독자가 행사 참여 조건을 비교하고 자신의 일정에 맞게 선택할 수 있는 주제입니다.',
        'draft': '테스트 전용 초안으로 현장 관측이나 실제 최신 보도를 의미하지 않습니다. ' * 10,
        'sources': [{'url': url, 'primary': index == 0, 'checked_at': NOW.isoformat(),
                     'support': 'Fixture-only source, not real event evidence.'}
                    for index, url in enumerate(('https://example.org/official', 'https://example.net/report'))],
        'claims': [{'text': '행사 참여 조건을 안내합니다.', 'source_url': 'https://example.org/official'}]}
        for n in range(5)], 'policy_sources': ['https://example.org/policy', 'https://example.net/policy']}, ensure_ascii=False)


def writing_response() -> str:
    sentence = '행사에 참여하기 전에 운영 시간과 신청 조건을 나누어 살펴보면 계획을 세우기 편해요. '
    return json.dumps({'title': '과학 행사, 참여 조건부터 알아볼까요?', 'lead': sentence,
        'summary': ['신청과 참여의 차이를 알아봐요.', '운영 시간을 살펴봐요.'],
        'sections': [{'heading': f'🔎 질문 {n}', 'paragraphs': [sentence * 5, sentence * 4],
                     'source_urls': ['https://example.org/official', 'https://example.org/guide']}
                    for n in range(4)], 'ending': sentence, 'category': '과학', 'home_topic': '과학',
        'tags': ['과학', '행사'], 'scenes': [{'brief': f'넓은 실험 공간에서 서로 다른 활동 {n}',
        'alt': f'테스트 장면 {n}'} for n in range(4)]}, ensure_ascii=False)


def evidence_response() -> str:
    return json.dumps({'candidate_id': 'candidate-0', 'sources': [
        {'url': 'https://example.org/guide', 'primary': True, 'checked_at': 'RUNTIME', 'access': 'full_text',
         'support': 'Initial submission requires an idea PDF; development follows selection.'}],
        'essential_facts': [{'topic': topic, 'status': 'confirmed',
            'detail': detail, 'source_urls': ['https://example.org/guide']}
            for topic, detail in (('answer', 'Submit an idea PDF initially, not a completed app.'),
                ('conditions', 'A data usage specification is also required.'),
                ('timeline', 'Development starts after document selection.'))]})


def media_response(directory: Path, generated: bool = True) -> str:
    (directory / 'media').mkdir(exist_ok=True)
    for n in range(1, 5):
        ppm = directory / f'media/fixture-{n}.ppm'
        _ = ppm.write_bytes(b'P6\n400 400\n255\n' + bytes((i * n) % 256 for i in range(400 * 400 * 3)))
        _ = subprocess.run(['/usr/bin/sips', '-s', 'format', 'jpeg', str(ppm), '--out',
                            str(directory / f'media/{n:02}.jpg')], capture_output=True, check=True)
    return json.dumps({'assets': [{'file': f'media/{n:02}.jpg', 'origin': 'generated' if generated else 'official',
        'source_url': 'generated' if generated else 'https://example.org/photo',
        'rights_basis': 'Fixture-only https://example.org/license; never a real publication asset.',
        'credit': 'Fixture organization', 'scene': f'Fixture scene {n}'} for n in range(1, 5)]})


class FixtureProvider:
    calls: list[str]
    approve: bool

    def __init__(self, approve: bool = True) -> None:
        self.calls = []
        self.approve = approve

    def __call__(self, request: StageRequest) -> StageResponse:
        self.calls.append(request.stage)
        match request.stage:
            case 'research':
                result = research_response()
            case 'opportunity':
                from tistory_growth_os.domain.common import array, as_object
                inputs = Fields(as_object(parse_json(request.prompt.split('\nCandidates:\n', 1)[1]), ''), '', ())
                result = json.dumps({'candidates': [{'candidate_id': text(Fields(as_object(raw, ''), '', ()), 'id'),
                    'signal_query': 'NONE', 'mapping_basis': 'Fixture has no RSS match',
                    'search_query': 'fixture query', 'results': [], 'limitations': 'Fixture only'}
                    for raw in array(inputs, 'candidates', True)]})
            case 'selection':
                result = json.dumps({'candidate_id': 'candidate-0', 'rationale': 'fixture choice'})
            case 'evidence':
                result = evidence_response()
            case 'writing':
                result = writing_response()
            case 'text_review':
                result = text_review_response(request)
            case 'media':
                result = media_response(request.directory, generated=False)
            case 'review':
                payload = request.prompt.split('\nPackage:\n', 1)[1]
                fields = Fields.parse(parse_json(payload), '',
                    ('subject_sha256', 'manifest', 'article', 'evidence', 'deterministic_checks'))
                result = json.dumps({'subject_sha256': text(fields, 'subject_sha256'), 'approved': self.approve,
                    'checks': {name: self.approve for name in CHECKS}, 'issues': [] if self.approve else ['fixture rejection']})
            case 'discovery' | 'decision' | 'edit':
                raise AssertionError('Legacy fixture does not implement editorial-v2')
            case _:
                assert_never(request.stage)
        return StageResponse(result, 'fixture-' + request.stage, ('image_generation',) if request.stage == 'media' else ())


def text_review_response(request: StageRequest) -> str:
    from tistory_growth_os.domain.common import array, as_object
    from tistory_growth_os.preparation.text_review import TEXT_CHECKS
    envelope = Fields(as_object(parse_json(request.prompt.split('\nText subject:\n', 1)[1]), ''), '', ())
    subject = Fields(as_object(parse_json(text(envelope, 'payload')), ''), '', ())
    return json.dumps({'subject_sha256': text(envelope, 'subject_sha256'), 'approved': True,
        'repair': {'scope': 'none', 'block_ids': []},
        'checks': {name: True for name in TEXT_CHECKS}, 'issues': [], 'blocks': [
            {'identity': text(Fields(as_object(raw, ''), '', ()), 'identity'),
             'no_factual_claims': False, 'claims': [
                 {'quote': text(Fields(as_object(raw, ''), '', ()), 'prose'),
                  'evidence_refs': ['research/0'], 'source_urls': ['https://example.org/official']}]}
            for raw in array(subject, 'blocks', True)]})
