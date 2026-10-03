from pathlib import Path

import pytest

from tests.preparation_fixture import FixtureProvider, NOW, research_response
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.contracts.json_ast import JsonArray, JsonMember, JsonObject, JsonString
from tistory_growth_os.contracts.json_decode import parse_json
from tistory_growth_os.contracts.json_encode import encode_json
from tistory_growth_os.domain.common import Fields, array
from tistory_growth_os.preparation.contracts import PreparationError, parse_research
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute


def one_candidate(*, duplicate: bool = False) -> str:
    fields = Fields.parse(parse_json(research_response()), '', ('candidates', 'policy_sources'))
    first = array(fields, 'candidates', True)[0]
    return encode_json(JsonObject((
        JsonMember('candidates', JsonArray((first, first) if duplicate else (first,))),
        JsonMember('policy_sources', fields.required('policy_sources')),
        JsonMember('search_notes', JsonString('One qualified candidate is sufficient.')),
        JsonMember('rejected_leads', JsonArray(())),
    )))


def test_one_qualified_candidate_is_sufficient() -> None:
    # Given one fully evidenced topic, when parsed, then no five-topic quota applies.
    assert len(parse_research(one_candidate(), NOW).candidates) == 1


def test_duplicate_candidates_remain_invalid() -> None:
    # Given repeated identities, when parsed, then reduced quota does not permit duplicates.
    with pytest.raises(PreparationError, match='duplicate_candidate_identity'):
        _ = parse_research(one_candidate(duplicate=True), NOW)


def test_single_topic_reaches_package_without_expansion(tmp_path: Path) -> None:
    # Given one eligible topic and the real pipeline with fixture external services,
    run, provider = prepared_run(tmp_path), FixtureProvider()

    def single(request: StageRequest) -> StageResponse:
        response = provider(request)
        if request.stage == 'research':
            return StageResponse(one_candidate(), response.session_id, response.tool_kinds)
        return response

    # When executing production and exact replay,
    package = execute(run, single)
    before = tuple(provider.calls)
    assert execute(run, single) == package
    # Then exactly one research and one article complete without further calls.
    assert before.count('research') == 1
    assert tuple(provider.calls) == before
    assert (package / 'article.html').is_file()


@pytest.mark.parametrize('changed', (False, True))
def test_legacy_request_replay_preserves_response_binding(tmp_path: Path, changed: bool) -> None:
    from tistory_growth_os.preparation.prompt_history import recorded_prompt
    from tistory_growth_os.preparation.storage import StageStore
    provider = FixtureProvider()
    store = StageStore(tmp_path, provider)
    original = store.run(StageRequest('research', 'legacy-request', tmp_path))
    if changed:
        _ = (tmp_path / 'research.json').write_text('{}')
    request = recorded_prompt(StageRequest('research', 'current-request', tmp_path), 'legacy-request')
    if changed:
        with pytest.raises(PreparationError, match='checkpoint_changed'):
            _ = store.run(request)
    else:
        assert store.run(request) == original
    assert provider.calls == ['research']
