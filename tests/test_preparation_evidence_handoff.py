from pathlib import Path
import pytest

from tests.preparation_fixture import FixtureProvider, evidence_response
from tests.preparation_fixture import NOW, research_response
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute
from tistory_growth_os.preparation.evidence import enrich_candidate
from tistory_growth_os.preparation.contracts import parse_research


def test_official_detail_pack_reaches_writer_and_exact_review(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()
    observed: list[str] = []

    def provider(request: StageRequest) -> StageResponse:
        if request.stage == 'evidence':
            return StageResponse(evidence_response(), 'fixture-evidence', ('web_search',))
        if request.stage in ('writing', 'review'):
            observed.append(request.prompt)
        return fixture(request)

    _ = execute(run, provider)
    assert len(observed) == 2
    assert all('A data usage specification is also required.' in item for item in observed)
    assert (run.directory / 'evidence.receipt.json').exists()


def test_unknown_central_conditions_stop_before_writing(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def provider(request: StageRequest) -> StageResponse:
        if request.stage == 'evidence':
            directory = request.directory.parent if request.directory.name == 'evidence-enrichment' else request.directory
            identity = 'candidate-' + str(int(directory.name) - 1) if directory.name in ('02', '03') else 'candidate-0'
            return StageResponse(evidence_response().replace('confirmed', 'unknown').replace('candidate-0', identity),
                                 'fixture-evidence', ('web_search',))
        return fixture(request)

    with pytest.raises(PreparationError, match='source_candidates_exhausted'):
        _ = execute(run, provider)
    assert 'writing' not in fixture.calls
    assert (run.directory / 'evidence-enrichment/evidence.receipt.json').exists()


@pytest.mark.parametrize(('before', 'after', 'reason'), [
    ('candidate-0', 'candidate-wrong', 'evidence_candidate_mismatch'),
    ('"timeline"', '"answer"', 'essential_fact_coverage_required'),
    ('"primary": true', '"primary": false', 'essential_fact_primary_source_required'),
    ('https://example.org/guide', 'http://127.0.0.1/guide', 'source_url_or_time_invalid'),
])
def test_detail_boundary_rejects_wrong_identity_coverage_or_source(before: str, after: str, reason: str) -> None:
    candidate = parse_research(research_response(), NOW).candidates[0]
    with pytest.raises(PreparationError, match=reason):
        _ = enrich_candidate(evidence_response().replace(before, after), candidate, NOW)
