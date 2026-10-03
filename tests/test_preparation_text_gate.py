from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

import pytest

from tests.preparation_fixture import FixtureProvider, NOW, evidence_response, research_response, writing_response, text_review_response
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.preparation.contracts import PreparationError, parse_research
from tistory_growth_os.preparation.evidence import enrich_candidate
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute
from tistory_growth_os.preparation.text_review import check_text_review, text_subject


def test_text_review_provider_schema_is_valid_json() -> None:
    from tistory_growth_os.contracts.json_decode import parse_json
    from tistory_growth_os.domain.common import Fields, text
    from tistory_growth_os.preparation.provider import SCHEMAS
    schema = Fields.parse(parse_json((SCHEMAS / 'text_review.json').read_text()), '',
                          ('type', 'additionalProperties', 'required', 'properties'))
    assert text(schema, 'type') == 'object'


def test_unreferenced_discovery_url_is_not_writing_eligible() -> None:
    candidate = parse_research(research_response(), NOW).candidates[0]
    candidate = replace(candidate, urls=candidate.urls + ('https://example.org/empty-faq',))
    enriched = enrich_candidate(evidence_response(), candidate, NOW)
    assert enriched.urls == ('https://example.org/guide', 'https://example.org/official')


def test_text_rejection_stops_before_media_or_package(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def reject(request: StageRequest) -> StageResponse:
        if request.stage == 'text_review':
            candidate = enrich_candidate(evidence_response(), parse_research(research_response(), NOW).candidates[0], NOW)
            subject = text_subject(writing_response(), candidate, NOW)
            return StageResponse(json.dumps({'subject_sha256': subject.digest, 'approved': False,
                'checks': {}, 'issues': ['Contradictory event wording and unsupported section links'],
                'blocks': [], 'repair': {'scope': 'none', 'block_ids': []}}), str(request.directory), ())
        return fixture(request)

    with pytest.raises(PreparationError, match='enrichment_budget_exhausted'):
        _ = execute(run, reject)
    assert 'media' not in fixture.calls
    assert not (run.directory / 'package').exists()


def test_each_section_retains_its_supporting_link() -> None:
    from tistory_growth_os.preparation.editorial import parse_draft
    candidate = enrich_candidate(evidence_response(), parse_research(research_response(), NOW).candidates[0], NOW)
    html = parse_draft(writing_response(), candidate).html
    assert html.count('href="https://example.org/official"') == 4


@pytest.mark.parametrize(('before', 'after', 'reason'), [
    ('"temporal_consistency": true', '"temporal_consistency": false', 'text_review_held'),
    ('"claim_support": true', '"claim_support": false', 'text_review_held'),
    ('"source_links": true', '"source_links": false', 'text_review_held'),
    ('"coverage": true', '"coverage": false', 'text_review_held'),
    ('"research/0"', '"research/99"', 'text_review_unknown_fact'),
    ('https://example.org/official', 'https://example.org/guide', 'text_review_claim_source_mismatch'),
    ('"identity": "lead"', '"identity": "title"', 'text_review_block_coverage'),
    ('"quote": "', '"quote": "NONMATCH-', 'text_review_quote_mismatch'),
    ('"no_factual_claims": false', '"no_factual_claims": true', 'text_review_claim_coverage'),
])
def test_invalid_text_evidence_cannot_approve(before: str, after: str, reason: str, tmp_path: Path) -> None:
    candidate = enrich_candidate(evidence_response(), parse_research(research_response(), NOW).candidates[0], NOW)
    subject = text_subject(writing_response(), candidate, NOW)
    request = StageRequest('text_review', '\nText subject:\n' + json.dumps({
        'subject_sha256': subject.digest, 'payload': subject.payload}), tmp_path)
    response = text_review_response(request).replace(before, after)
    with pytest.raises(PreparationError, match=reason):
        check_text_review(response, subject)


def test_changed_text_cannot_reuse_text_approval(tmp_path: Path) -> None:
    candidate = enrich_candidate(evidence_response(), parse_research(research_response(), NOW).candidates[0], NOW)
    subject = text_subject(writing_response(), candidate, NOW)
    request = StageRequest('text_review', '\nText subject:\n' + json.dumps({
        'subject_sha256': subject.digest, 'payload': subject.payload}), tmp_path)
    changed = text_subject(writing_response().replace('계획', '일정'), candidate, NOW)
    with pytest.raises(PreparationError, match='text_review_subject_mismatch'):
        check_text_review(text_review_response(request), changed)


def test_writer_cannot_approve_pre_media_text(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def same_session(request: StageRequest) -> StageResponse:
        response = fixture(request)
        return replace(response, session_id='writer') if request.stage in ('writing', 'text_review') else response

    with pytest.raises(PreparationError, match='independent_text_review_session_required'):
        _ = execute(run, same_session)
    assert 'media' not in fixture.calls


def test_fact_repair_gets_new_text_binding(tmp_path: Path) -> None:
    from tests.test_preparation_repair import repair_provider
    run = prepared_run(tmp_path)
    _ = execute(run, repair_provider)
    assert (run.directory / 'text-repair/text_review.receipt.json').is_file()


def test_issue_aging_during_text_review_continues_media(tmp_path: Path) -> None:
    fixture, clock = FixtureProvider(), [NOW]
    run = replace(prepared_run(tmp_path), clock=lambda: clock[0])

    def elapsed(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if request.stage == 'text_review':
            clock[0] = NOW + timedelta(hours=24)
        return response

    package = execute(run, elapsed)
    assert package.is_dir()
    assert 'media' in fixture.calls
