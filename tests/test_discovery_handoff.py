from dataclasses import replace
from pathlib import Path

import pytest

from tests.preparation_fixture import FixtureProvider, NOW, research_response
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.contracts.json_ast import JsonArray, JsonMember, JsonObject
from tistory_growth_os.contracts.json_decode import parse_json
from tistory_growth_os.contracts.json_encode import encode_json
from tistory_growth_os.domain.common import Fields, array, as_object
from tistory_growth_os.preparation.contracts import PreparationError, parse_research
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute


def provisional_research() -> str:
    fields = Fields(as_object(parse_json(research_response()), ''), '', ())
    single = JsonObject(tuple(JsonMember(member.key,
        JsonArray(array(fields, 'candidates', True)[:1]) if member.key == 'candidates' else member.value)
        for member in fields.value.members))
    return encode_json(single).replace('"support":', '"access": "search_lead", "support":')


def test_provisional_source_urls_reach_evidence_before_final_selection(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def provider(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if request.stage == 'research':
            return replace(response, response=provisional_research())
        if request.stage == 'evidence':
            assert 'https://example.org/official' in request.source_urls
        return response

    package = execute(run, provider)
    assert package.name == 'package'
    assert fixture.calls.index('evidence') < fixture.calls.index('selection')


def test_provisional_sources_do_not_bypass_primary_body_gate(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def provider(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if request.stage == 'research':
            return replace(response, response=provisional_research())
        if request.stage == 'evidence':
            return replace(response, response=response.response.replace('full_text', 'unavailable'))
        return response

    with pytest.raises(PreparationError, match='source_candidates_exhausted'):
        _ = execute(run, provider)
    assert 'selection' not in fixture.calls
    assert 'writing' not in fixture.calls
    assert not (run.directory / 'package').exists()


def test_research_cannot_assert_host_verified_access() -> None:
    with pytest.raises(PreparationError, match='research_access_invalid'):
        _ = parse_research(provisional_research().replace('search_lead', 'full_text'), NOW)
