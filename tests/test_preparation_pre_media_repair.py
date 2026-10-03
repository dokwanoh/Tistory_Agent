from dataclasses import replace
from pathlib import Path

import pytest
from typing_extensions import override

from tests.preparation_fixture import FixtureProvider
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute


class RepairFixture(FixtureProvider):
    failure: str = ''

    @override
    def __call__(self, request: StageRequest) -> StageResponse:
        response = super().__call__(request)
        repaired = request.directory.name in ('pre-media-repair', 'text-repair')
        response = replace(response, session_id=response.session_id + ('-repair' if repaired else ''))
        if self.failure in ('second_rejection', 'final_facts'):
            response = replace(response, session_id=str(request.directory) + '-' + request.stage)
        if self.failure == 'self_review' and repaired and request.stage == 'text_review':
            response = replace(response, session_id='fixture-writing-repair')
        if self.failure == 'reused_final_reviewer' and request.stage == 'review':
            response = replace(response, session_id='fixture-text_review-repair')
        if request.stage == 'text_review' and (not repaired or self.failure == 'second_rejection'):
            result = response.response.replace('"approved": true', '"approved": false')
            result = result.replace('"temporal_consistency": true', '"temporal_consistency": false')
            result = result.replace('"issues": []', '"issues": ["lead has contradictory tense"]')
            result = result.replace('"scope": "none", "block_ids": []',
                '"scope": "temporal_source_binding", "block_ids": ["lead"]')
            if self.failure == 'broader_failure':
                result = result.replace('"reader_value": true', '"reader_value": false')
            return replace(response, response=result)
        if request.stage == 'writing' and repaired:
            result = response.response.replace('"lead": "', '"lead": "지금은 ')
            if self.failure == 'scope_change':
                result = result.replace('"ending": "', '"ending": "변경 ')
            return replace(response, response=result)
        if request.stage == 'review' and self.failure == 'final_facts':
            return replace(response, response=response.response.replace('"approved": true', '"approved": false')
                .replace('"facts": true', '"facts": false').replace('"issues": []', '"issues": ["unsupported claim"]'))
        return response


def test_pre_media_repair_rechecks_then_produces_package(tmp_path: Path) -> None:
    run, provider = prepared_run(tmp_path), RepairFixture()
    package = execute(run, provider)
    assert package.is_dir()
    assert provider.calls == ['research', 'opportunity', 'evidence', 'selection', 'writing', 'text_review',
        'writing', 'text_review', 'media', 'review']
    assert (run.directory / 'pre-media-repair/text_review.receipt.json').exists()
    assert '지금은' in (package / 'article.html').read_text()
    before = list(provider.calls)
    assert execute(run, provider) == package
    assert provider.calls == before


@pytest.mark.parametrize(('failure', 'reason'), [('second_rejection', 'enrichment_budget_exhausted'),
    ('scope_change', 'pre_media_repair_scope_changed'),
    ('self_review', 'independent_text_review_session_required')])
def test_ineligible_or_failed_repair_never_produces_media(failure: str, reason: str, tmp_path: Path) -> None:
    run, provider = prepared_run(tmp_path), RepairFixture()
    provider.failure = failure
    with pytest.raises(PreparationError, match=reason):
        _ = execute(run, provider)
    assert 'media' not in provider.calls
    assert provider.calls.count('writing') <= 3
    assert not (run.directory / 'package').exists()


@pytest.mark.parametrize(('failure', 'reason'), [('final_facts', 'independent_review_held'),
    ('reused_final_reviewer', 'independent_review_session_required')])
def test_final_failure_never_promotes_without_independent_pass(failure: str, reason: str, tmp_path: Path) -> None:
    run, provider = prepared_run(tmp_path), RepairFixture()
    provider.failure = failure
    with pytest.raises(PreparationError, match=reason):
        _ = execute(run, provider)
    assert provider.calls.count('writing') == (3 if failure == 'final_facts' else 2)
    assert not (run.directory / 'package').exists()


def test_coverage_failure_receives_editorial_enrichment(tmp_path: Path) -> None:
    run, provider = prepared_run(tmp_path), RepairFixture()
    provider.failure = 'broader_failure'
    assert execute(run, provider).is_dir()
    assert provider.calls.count('writing') == 2
