from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from typing import assert_never

import pytest

from tests.preparation_fixture import NOW, media_response, writing_response
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.contracts.json_decode import parse_json
from tistory_growth_os.domain.common import Fields, as_object, text
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import PreparationRun, execute
from tistory_growth_os.preparation.shared_sources import SourceDocument, SourceReader
from tistory_growth_os.preparation.v2_prompts import POLICY_URLS


URL = 'https://example.org/official'
GUIDE = 'https://example.org/guide'
BODY = '행사에 참여하기 전에 운영 시간과 신청 조건을 나누어 살펴보면 계획을 세우기 편해요. ' * 12


def v2_run(root: Path) -> PreparationRun:
    run = prepared_run(root)
    initial = run.directory / 'input.json'
    _ = initial.write_text('{"workflow_version":"editorial-v2",' + initial.read_text()[1:])
    reader = SourceReader(run.directory / 'shared-sources')
    for url in (URL, GUIDE, *POLICY_URLS):
        reader.remember(SourceDocument(url, NOW.isoformat(), 'full_text', BODY,
            sha256(BODY.encode()).hexdigest(), sha256(b'fixture response').hexdigest(), ()))
    return run


class EditorialFixture:
    """Mutable fixture records calls and supplies explicit editorial actions."""
    def __init__(self, actions: tuple[str, ...] = ()) -> None:
        self.calls: list[str] = []
        self.actions: list[str] = list(actions)

    def __call__(self, request: StageRequest) -> StageResponse:
        self.calls.append(request.stage)
        match request.stage:
            case 'discovery':
                result = json.dumps({'candidates': [{'id': 'candidate-0', 'title': '과학 행사',
                    'event_at': '2026-09-21T00:00:00+00:00', 'event_time_basis': '새 공지 시각',
                    'reader_question': '어떻게 참여하나요?', 'source_urls': [URL, GUIDE]}]})
            case 'opportunity':
                result = json.dumps({'candidates': [{'candidate_id': 'candidate-0', 'signal_query': 'NONE',
                    'mapping_basis': 'fixture', 'search_query': '과학 행사', 'results': [], 'limitations': 'fixture'}]})
            case 'decision':
                result = json.dumps({'candidate_id': 'candidate-0', 'angle': '참여 전 알아둘 조건',
                    'facts': [{'claim': '운영 시간과 신청 조건을 확인해요.', 'source_url': URL,
                               'source_quote': '운영 시간과 신청 조건'}], 'reason': '독자에게 유용한 공지'})
            case 'writing':
                result = writing_response()
            case 'media':
                result = media_response(request.directory, generated=False)
            case 'edit':
                envelope = Fields(as_object(parse_json(request.prompt.split('\nEditorial input:\n')[1]), ''), '', ())
                action = self.actions.pop(0) if self.actions else 'ready'
                writing = text(envelope, 'writing')
                if action == 'revise':
                    writing = writing.replace('과학 행사, 참여 조건부터 알아볼까요?', '수정한 제목, 참여 조건부터 알아봐요')
                result = json.dumps({'action': action, 'subject_sha256': text(envelope, 'subject_sha256'),
                    'writing': None,
                    'source_urls': [], 'notes': '본문·이미지·권리·시점·독창성을 확인했습니다. Fixture only.',
                    'claims': [{'article_quote': '운영 시간과 신청 조건', 'source_url': URL,
                                'source_quote': '운영 시간과 신청 조건'}] if action == 'ready' else []}, ensure_ascii=False)
                if action == 'revise':
                    result = result.replace('"writing": null', '"writing": ' + writing)
            case 'research' | 'selection' | 'evidence' | 'text_review' | 'review':
                raise AssertionError(request.stage)
            case _:
                assert_never(request.stage)
        return StageResponse(result, 'fixture-' + request.stage + '-' + request.directory.name, ())


def test_v2_uses_editor_not_boolean_review_and_replays(tmp_path: Path) -> None:
    run, provider = v2_run(tmp_path), EditorialFixture()
    package = execute(run, provider)
    assert provider.calls == ['discovery', 'opportunity', 'decision', 'writing', 'media', 'edit']
    assert package.is_dir()
    again = EditorialFixture()
    assert execute(run, again) == package
    assert again.calls == []
    assert len(list((tmp_path / 'contracts/reviews').glob('*.json'))) == 1


def test_interactive_media_pauses_after_writing_with_scene_checkpoint(tmp_path: Path) -> None:
    run, provider = v2_run(tmp_path), EditorialFixture()
    initial = json.loads((run.directory / 'input.json').read_text())
    initial['media_mode'] = 'interactive'
    _ = (run.directory / 'input.json').write_text(json.dumps(initial))
    with pytest.raises(PreparationError, match='interactive_media_required'):
        _ = execute(run, provider)
    assert provider.calls == ['discovery', 'opportunity', 'decision', 'writing']
    pending = next(run.directory.glob('candidate-01/interactive-media.pending.json'))
    payload = json.loads(pending.read_text())
    assert payload['kind'] == 'interactive_media_pending'
    assert len(payload['scenes']) == 4
    assert not (run.directory / 'candidate-01/media.receipt.json').exists()


def test_v2_editor_changes_title_without_writer_replay(tmp_path: Path) -> None:
    run, provider = v2_run(tmp_path), EditorialFixture(('revise',))
    package = execute(run, provider)
    assert '수정한 제목' in (package / 'manifest.json').read_text()
    assert provider.calls.count('writing') == 1
    assert provider.calls.count('edit') == 2


def test_v2_invalid_review_record_gets_record_repair(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture()
    attempts: list[str] = []

    def provider(request: StageRequest) -> StageResponse:
        result = fixture(request)
        if request.stage == 'edit':
            attempts.append(request.stage)
            if len(attempts) == 1:
                return StageResponse(result.response.replace('운영 시간과 신청 조건', '원문에 없는 인용'),
                                     result.session_id, ())
        return result

    assert execute(run, provider).is_dir()
    assert len(attempts) == 2
    assert fixture.calls.count('writing') == 1


def test_v2_editor_budget_persists_and_does_not_publish(tmp_path: Path) -> None:
    run = v2_run(tmp_path)
    for provider in (EditorialFixture(('revise',) * 4), EditorialFixture()):
        with pytest.raises(PreparationError, match='editorial_budget_exhausted'):
            _ = execute(run, provider)
    assert not list(run.directory.glob('**/package'))
    assert not (tmp_path / 'contracts/reviews').exists()


def test_v2_cannot_approve_writer_session(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture()

    def provider(request: StageRequest) -> StageResponse:
        result = fixture(request)
        return StageResponse(result.response, 'same' if request.stage in ('writing', 'edit')
                             else result.session_id, ())

    with pytest.raises(PreparationError, match='independent_review_session_required'):
        _ = execute(run, provider)


def test_v2_changed_source_body_is_not_reused(tmp_path: Path) -> None:
    run = v2_run(tmp_path)
    reader = SourceReader(run.directory / 'shared-sources')
    raw = asdict(reader.read(URL))
    raw['body'] = 'changed'
    _ = reader.path(URL).write_text(json.dumps(raw))
    with pytest.raises(PreparationError, match='source_snapshot_changed'):
        _ = execute(run, EditorialFixture())
