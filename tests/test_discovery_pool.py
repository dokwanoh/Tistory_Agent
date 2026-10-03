from dataclasses import replace
import json
from pathlib import Path

import pytest

from tests.preparation_fixture import NOW
from tests.test_preparation_v2 import EditorialFixture, GUIDE, URL, v2_run
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.runner import execute
from tistory_growth_os.preparation.v2_sources import discover


@pytest.mark.parametrize('defect', ['date', 'url'])
def test_bad_lead_does_not_discard_valid_sibling(defect: str) -> None:
    lead = {'id': 'valid-event', 'title': '유효한 사건', 'event_at': NOW.isoformat(),
            'event_time_basis': '공식 발표', 'reader_question': '변경사항은?', 'source_urls': [URL]}
    bad = {**lead, 'id': 'invalid-event'}
    if defect == 'date':
        bad['event_at'] = '2026-09-21'
    else:
        bad['source_urls'] = ['not-a-url']

    choices = discover(json.dumps({'candidates': [bad, lead]}), NOW)

    assert [item.candidate_id for item in choices] == ['valid-event']


def test_denied_destination_remains_a_hold() -> None:
    lead = {'id': 'unsafe-event', 'title': '사건', 'event_at': NOW.isoformat(),
            'event_time_basis': '발표', 'reader_question': '변경사항은?',
            'source_urls': ['https://127.0.0.1/private']}

    with pytest.raises(PreparationError, match='source_destination_denied'):
        _ = discover(json.dumps({'candidates': [lead]}), NOW)


def test_editor_replacement_reuses_other_collected_candidate(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture(('replace_topic',))
    initial = run.directory / 'input.json'
    _ = initial.write_text(initial.read_text().replace('editorial-v2', 'editorial-simple-v1'))

    def provider(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if request.stage == 'discovery':
            leads = [{'id': f'candidate-{i}', 'title': f'이슈 {i}', 'event_at': NOW.isoformat(),
                      'event_time_basis': '공식 발표', 'reader_question': f'질문 {i}',
                      'source_urls': [URL, GUIDE]} for i in range(2)]
            return replace(response, response=json.dumps({'candidates': leads}))
        if request.stage == 'decision' and request.directory.name == 'candidate-02':
            return replace(response, response=response.response.replace('candidate-0', 'candidate-1'))
        return response

    package = execute(run, provider)

    assert (package / 'article.html').is_file()
    assert fixture.calls.count('discovery') == 1
    assert fixture.calls.count('decision') == 2
    replay = EditorialFixture()
    assert execute(run, replay) == package
    assert replay.calls == []


def test_duplicate_leads_are_collapsed_before_selection() -> None:
    lead = {'id': 'same-event', 'title': '같은 사건',
            'event_at': NOW.isoformat(), 'event_time_basis': '공식 발표',
            'reader_question': '어떤 변화인가요?', 'source_urls': [URL]}
    raw = json.dumps({'candidates': [lead, lead, {**lead, 'id': 'other-id'}]})

    choices = discover(raw, NOW)

    assert len(choices) == 1


def test_fifth_readable_candidate_produces_only_one_article(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture()
    initial = run.directory / 'input.json'
    _ = initial.write_text(initial.read_text().replace('editorial-v2', 'editorial-simple-v1'))

    def provider(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if request.stage == 'discovery':
            leads = [{'id': f'candidate-{i}', 'title': f'이슈 {i}',
                      'event_at': '2026-09-01T00:00:00+00:00' if i < 4 else NOW.isoformat(), 'event_time_basis': '공식 발표',
                      'reader_question': f'질문 {i}',
                      'source_urls': [URL, GUIDE]} for i in range(5)]
            return replace(response, response=json.dumps({'candidates': leads}))
        if request.stage == 'decision':
            return replace(response, response=response.response.replace('candidate-0', 'candidate-4'))
        return response

    package = execute(run, provider)

    assert (package / 'article.html').is_file()
    assert fixture.calls.count('discovery') == 1
    assert fixture.calls.count('writing') == 1
    assert fixture.calls.count('media') == 1
