import json
from hashlib import sha256

import pytest

from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.decision_spans import DecisionSpans
from tistory_growth_os.contracts.json_decode import JsonDecodeError
from tistory_growth_os.preparation.v2_sources import selection_record


def test_none_with_empty_angle_reaches_candidate_reselection() -> None:
    # Given a valid rejection with no proposed article angle.
    raw = '{"candidate_id":"NONE","angle":"","reason":"unsupported","facts":[]}'
    # When the provider boundary and selection boundary consume it.
    resolved = DecisionSpans(()).resolve(raw)
    # Then it remains a rejection, not an exception or a selected article.
    assert json.loads(resolved) == json.loads(raw)
    assert selection_record(resolved, (), ()) is None


def test_selected_candidate_still_requires_nonempty_angle() -> None:
    # Given an actual selection missing its angle.
    raw = '{"candidate_id":"candidate","angle":"","reason":"supported","facts":[]}'
    # When either boundary parses it, then selection remains invalid.
    with pytest.raises(JsonDecodeError):
        _ = DecisionSpans(()).resolve(raw)
    with pytest.raises(JsonDecodeError):
        _ = selection_record(raw, (), ())


def source(body: str, url: str = 'https://example.org/source') -> str:
    captured = body if len(body) >= 200 else body + '\n' + '추가 공식 안내입니다. ' * 25
    return json.dumps({'documents': [{'url': url, 'access': 'full_text', 'body': captured,
        'body_sha256': sha256(captured.encode()).hexdigest(), 'response_sha256': 'a' * 64,
        'checked_at': '2026-09-25T00:00:00+00:00', 'links': [], 'published_at': '', 'title': ''}]})


def selection(span_id: str) -> str:
    return json.dumps({'candidate_id': 'candidate', 'angle': 'angle', 'reason': 'reason',
        'facts': [{'claim': '기간은 4일이다.', 'span_id': span_id}]})


def test_selected_span_is_copied_from_original_without_model_quote() -> None:
    catalog = DecisionSpans.from_sources(source('제목\n\n9월 24일부터 27일까지\n  통행료 면제'))
    span = next(item for item in catalog.spans if item.quote == '9월 24일부터 27일까지')
    resolved = catalog.resolve(selection(span.identity))
    assert '9월 24일부터 27일까지' in resolved
    assert 'https://example.org/source' in resolved
    assert 'source_quote' in resolved
    assert 'span_id' not in resolved


def test_changed_source_or_url_cannot_reuse_span_id() -> None:
    original = DecisionSpans.from_sources(source('정확한 원문입니다.'))
    for raw in (source('변경된 원문입니다.'), source('정확한 원문입니다.', 'https://example.org/other')):
        with pytest.raises(PreparationError, match='decision_span_unknown'):
            _ = DecisionSpans.from_sources(raw).resolve(selection(original.spans[0].identity))


def test_unknown_span_rejected_and_none_decision_preserved() -> None:
    catalog = DecisionSpans.from_sources(source('정확한 원문입니다.'))
    with pytest.raises(PreparationError, match='decision_span_unknown'):
        _ = catalog.resolve(selection('invented'))
    raw = '{"candidate_id":"NONE","angle":"none","reason":"unsupported","facts":[]}'
    assert json.loads(catalog.resolve(raw)) == json.loads(raw)


def test_unicode_and_long_source_spans_remain_exact() -> None:
    body = '한글 날짜\n' + '긴 원문 ' * 250
    catalog = DecisionSpans.from_sources(source(body))
    assert all(item.quote in body and len(item.quote) <= 500 for item in catalog.spans)
    assert len({item.identity for item in catalog.spans}) == len(catalog.spans)
    assert 'enum' in catalog.schema()
