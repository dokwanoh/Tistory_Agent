from pathlib import Path

import pytest

from tistory_growth_os.contracts.json_ast import JsonArray, JsonMember, JsonObject
from tistory_growth_os.contracts.json_decode import parse_json
from tistory_growth_os.contracts.json_encode import encode_json
from tistory_growth_os.domain.common import Fields, array, as_object

from tests.preparation_fixture import FixtureProvider, evidence_response, research_response
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute


def test_next_candidate_reaches_one_package_and_replays(tmp_path: Path) -> None:
    # Given the first candidate's official body remains unreadable after enrichment.
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def provider(request: StageRequest) -> StageResponse:
        if request.stage == 'evidence':
            alternate = 'candidate-1' in request.prompt and 'candidate-0' not in request.prompt
            body = evidence_response().replace('candidate-0', 'candidate-1') if alternate else evidence_response().replace('confirmed', 'unknown')
            return StageResponse(body, str(request.directory), ('web_search',))
        response = fixture(request)
        if request.stage == 'selection':
            return StageResponse(response.response.replace('candidate-0', 'candidate-1'), response.session_id, ())
        return response

    # When one preparation runs and its immutable result is replayed.
    package = execute(run, provider)
    replay = FixtureProvider()
    assert execute(run, replay) == package
    # Then exactly one article was written and no replay calls or rejected-state resets occur.
    assert fixture.calls.count('writing') == 1
    assert replay.calls == []
    assert (run.directory / 'evidence-enrichment/evidence.json').is_file()
    assert (run.directory / 'source-candidates/02/evidence.json').is_file()


def test_exhausted_single_candidate_triggers_fresh_research(tmp_path: Path) -> None:
    # Given only one initial candidate whose official details cannot be read.
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def provider(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if request.stage == 'research':
            original = Fields(as_object(parse_json(research_response()), ''), '', ())
            raw = encode_json(JsonObject(tuple(JsonMember(member.key,
                JsonArray(array(original, 'candidates', True)[:1]) if member.key == 'candidates'
                else member.value) for member in original.value.members)))
            if request.directory.name == 'source-reselection':
                raw = raw.replace('candidate-0', 'replacement-0').replace('공공과학 행사', '새로운 과학 전시').replace('example.org', 'replacement.org').replace('example.net', 'replacement.net')
            return StageResponse(raw, str(request.directory), ('web_search',))
        if request.stage == 'evidence':
            replacement = 'replacement-0' in request.prompt
            raw = evidence_response().replace('candidate-0', 'replacement-0') if replacement else evidence_response().replace('confirmed', 'unknown')
            return StageResponse(raw, str(request.directory), ('web_search',))
        if request.stage == 'selection':
            return StageResponse(response.response.replace('candidate-0', 'replacement-0'), response.session_id, ())
        if request.stage == 'writing':
            return StageResponse(response.response.replace('example.org/official', 'replacement.org/official'), response.session_id, ())
        if request.stage == 'text_review':
            return StageResponse(response.response.replace('example.org/official', 'replacement.org/official'), response.session_id, response.tool_kinds)
        return response

    # When the same operation replaces its failed topic through new source research.
    package = execute(run, provider)
    # Then its single output retains the original operation identity and replacement evidence.
    assert package.is_dir()
    assert (run.directory / 'source-reselection/research.receipt.json').is_file()
    assert 'replacement-0' in (run.directory / 'selection.json').read_text()
    assert fixture.calls.count('writing') == 1


def test_uncertain_evidence_attempt_never_switches_candidate(tmp_path: Path) -> None:
    # Given an evidence call may already have happened but has no recorded result.
    run, fixture = prepared_run(tmp_path), FixtureProvider()
    _ = (run.directory / 'evidence.attempt').write_text('uncertain')
    # When executing, then integrity uncertainty stops before any alternate source research.
    with pytest.raises(PreparationError, match='stage_attempt_uncertain'):
        _ = execute(run, fixture)
    assert fixture.calls == ['research', 'opportunity']
    assert not (run.directory / 'source-candidates').exists()
