from dataclasses import replace
from pathlib import Path

import pytest
from typing_extensions import override

from tests.preparation_fixture import FixtureProvider
from tests.preparation_fixture import NOW, evidence_response, research_response, writing_response
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.contracts import parse_research
from tistory_growth_os.preparation.evidence import enrich_candidate
from tistory_growth_os.preparation.editorial import parse_draft


class EnrichmentFixture(FixtureProvider):
    mode: str = 'link'

    @override
    def __call__(self, request: StageRequest) -> StageResponse:
        response = super().__call__(request)
        response = replace(response, session_id=str(request.directory) + '-' + request.stage)
        if request.stage == 'evidence' and self.mode == 'evidence' and request.directory.name != 'evidence-enrichment':
            return replace(response, response=response.response.replace('"confirmed"', '"unknown"'))
        if request.stage == 'writing' and self.mode == 'summary' and request.directory.name != 'pre-media-repair':
            return replace(response, response=response.response.replace(
                '["신청과 참여의 차이를 알아봐요.", "운영 시간을 살펴봐요."]', '["요약 하나"]'))
        if request.stage == 'writing' and request.directory.name != 'pre-media-repair':
            return replace(response, response=response.response.replace(
                '["https://example.org/official", "https://example.org/guide"]',
                '["https://example.org/guide"]', 1))
        if request.stage == 'text_review' and request.directory.name != 'pre-media-repair':
            if self.mode == 'record':
                return replace(response, response=response.response.replace('"quote": "', '"quote": "WRONG '))
            if self.mode in ('voice', 'persistent'):
                return replace(response, response=response.response.replace('"approved": true', '"approved": false')
                    .replace('"voice": true', '"voice": false')
                    .replace('"issues": []', '"issues": ["Explain in reader-friendly prose"]'))
            if self.mode == 'new_evidence':
                return replace(response, response=response.response.replace('"approved": true', '"approved": false')
                    .replace('"claim_support": true', '"claim_support": false')
                    .replace('"issues": []', '"issues": ["Reopen official detail to substantiate the answer"]'))
        if self.mode == 'persistent' and request.stage == 'text_review':
            return replace(response, response=response.response.replace('"approved": true', '"approved": false')
                .replace('"voice": true', '"voice": false')
                .replace('"issues": []', '"issues": ["Explain in reader-friendly prose"]'))
        return response


def test_missing_body_source_is_supplemented_and_independently_reviewed(tmp_path: Path) -> None:
    # Given a reviewer identifying a verified supporting link missing from the section.
    run, provider = prepared_run(tmp_path), EnrichmentFixture()
    # When preparation runs through the ordinary executor.
    package = execute(run, provider)
    # Then the link is added before a new review and before media, with replay preserved.
    assert 'href="https://example.org/official"' in (package / 'article.html').read_text()
    assert provider.calls == ['research', 'opportunity', 'evidence', 'selection', 'writing', 'text_review',
                              'writing', 'text_review', 'media', 'review']
    previous = list(provider.calls)
    assert execute(run, provider) == package
    assert provider.calls == previous


def test_voice_failure_is_reworked_instead_of_immediate_termination(tmp_path: Path) -> None:
    # Given an editorial defect outside the historical tense-only correction scope.
    run, provider = prepared_run(tmp_path), EnrichmentFixture()
    provider.mode = 'voice'
    # When the writer fixes it and the independent grader accepts the revised bytes.
    package = execute(run, provider)
    # Then only the re-reviewed package is delivered.
    assert package.is_dir()
    assert (run.directory / 'pre-media-repair/text_review.receipt.json').is_file()


@pytest.mark.parametrize('mode', ['summary', 'evidence', 'record'])
def test_pre_review_defect_gets_targeted_enrichment(mode: str, tmp_path: Path) -> None:
    run, provider = prepared_run(tmp_path), EnrichmentFixture()
    provider.mode = mode
    package = execute(run, provider)
    assert package.is_dir()


def test_persistent_rejection_preserves_work_without_media_or_approval(tmp_path: Path) -> None:
    run, provider = prepared_run(tmp_path), EnrichmentFixture()
    provider.mode = 'persistent'
    with pytest.raises(PreparationError, match='enrichment_budget_exhausted'):
        _ = execute(run, provider)
    assert provider.calls.count('writing') == 3
    assert 'media' not in provider.calls
    assert not list(run.directory.rglob('package'))


def test_one_genuinely_supporting_source_does_not_require_link_padding() -> None:
    candidate = enrich_candidate(evidence_response(), parse_research(research_response(), NOW).candidates[0], NOW)
    writing = writing_response().replace('["https://example.org/official", "https://example.org/guide"]',
                                          '["https://example.org/guide"]')
    assert 'href="https://example.org/guide"' in parse_draft(writing, candidate).html


def test_missing_claim_support_researches_before_rewriting(tmp_path: Path) -> None:
    run, provider = prepared_run(tmp_path), EnrichmentFixture()
    provider.mode = 'new_evidence'
    assert execute(run, provider).is_dir()
    assert provider.calls.count('evidence') == 2
    assert (run.directory / 'pre-media-repair/evidence.receipt.json').is_file()
