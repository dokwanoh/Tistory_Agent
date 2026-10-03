from dataclasses import replace
from pathlib import Path

import pytest

from tests.preparation_fixture import NOW, FixtureProvider, research_response
from tistory_growth_os.preparation.contracts import PreparationError, parse_research
from tistory_growth_os.preparation.enrichment import TextContext, verified_detail
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.storage import StageStore
from tistory_growth_os.contracts.json_ast import JsonArray, JsonMember, JsonObject, JsonString


@pytest.mark.parametrize('corrected', [True, False])
def test_invalid_diagnostic_source_gets_bounded_record_repair(tmp_path: Path, corrected: bool) -> None:
    fixture = FixtureProvider()

    def provider(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if not corrected or request.directory == tmp_path:
            response = replace(response, response=response.response.replace('"sources": [',
                '"sources": [{"url":"https://example.org:30443/chat",'
                + '"primary":true,"checked_at":"RUNTIME","access":"unavailable",'
                + '"support":"Attempt failed; not supporting evidence"},', 1))
        return response

    store = StageStore(tmp_path, provider)
    candidate = parse_research(research_response(), NOW).candidates[0]
    context = TextContext(candidate, lambda: NOW, frozenset())
    _ = store.run(StageRequest('evidence', 'fixture', tmp_path))
    if corrected:
        result = verified_detail(store, context)
        assert all(':30443' not in url for url in result.urls)
        assert verified_detail(store, context) == result
    else:
        with pytest.raises(PreparationError, match='evidence_enrichment_exhausted'):
            _ = verified_detail(store, context)
    assert fixture.calls == ['evidence', 'evidence']
    assert ':30443' in (tmp_path / 'evidence.json').read_text()


def test_captured_body_reading_authority_reaches_evidence_enrichment(tmp_path: Path) -> None:
    fixture = FixtureProvider()
    candidate = parse_research(research_response(), NOW).candidates[0]
    snapshot = JsonObject((JsonMember('body', JsonString('호스트가 실제 수집한 공식 본문')),))
    candidate = replace(candidate, evidence=JsonObject(candidate.evidence.members + (
        JsonMember('source_snapshots', JsonArray((snapshot,))),)))

    def provider(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if request.directory == tmp_path:
            return replace(response, response=response.response.replace('"confirmed"', '"unknown"'))
        assert set(request.source_urls) == {*candidate.urls, 'https://example.org/guide'}
        return response

    store = StageStore(tmp_path, provider)
    _ = store.run(StageRequest('evidence', 'fixture', tmp_path))
    context = TextContext(candidate, lambda: NOW, frozenset())
    result = verified_detail(store, context)
    assert result.evidence.get('official_detail') is not None
    assert result.evidence.get('source_snapshots') == candidate.evidence.get('source_snapshots')
    assert verified_detail(store, context) == result
    assert fixture.calls == ['evidence', 'evidence']
