from dataclasses import replace
import json
from pathlib import Path

import pytest

from tests.preparation_fixture import FixtureProvider, writing_response
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.preparation.contracts import CHECKS, PreparationError, text_repair_eligible
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute


def repair_provider(request: StageRequest) -> StageResponse:
    response = FixtureProvider()(request)
    if request.stage == 'review' and request.directory.name != 'text-repair':
        source = response.response.replace('"approved": true', '"approved": false')
        source = source.replace('"facts": true', '"facts": false')
        source = source.replace('"issues": []', '"issues": ["Remove unsupported factual assertion"]')
        return replace(response, response=source)
    if request.stage == 'writing' and request.directory.name == 'text-repair':
        return replace(response, response=writing_response().replace('계획을 세우기 편해요', '일정을 준비하기 편해요'),
                       session_id='repair-writing')
    return replace(response, session_id=request.directory.name + '-' + request.stage)


def test_fact_only_failure_gets_one_fresh_review_without_overwriting_original(tmp_path: Path) -> None:
    # Given a valid article whose first independent review finds a factual error.
    run = prepared_run(tmp_path)
    # When the pipeline performs its bounded text repair.
    package = execute(run, repair_provider)
    # Then only the revised, independently reviewed bytes are promoted.
    assert package == run.directory / 'text-repair/package'
    assert '"approved": false' in (run.directory / 'review.json').read_text()
    assert not (run.directory / 'package').exists()
    assert '일정을 준비하기 편해요' in (package / 'article.html').read_text()
    assert len(list((tmp_path / 'contracts/reviews').glob('*.json'))) == 1
    for number in range(1, 5):
        name = f'media/{number:02}.jpg'
        assert (package / name).read_bytes() == (run.directory / name).read_bytes()


def test_second_failed_review_does_not_loop_or_promote(tmp_path: Path) -> None:
    # Given a repair that is also rejected by its independent reviewer.
    run = prepared_run(tmp_path)
    calls: list[str] = []

    def reject(request: StageRequest) -> StageResponse:
        calls.append(request.stage)
        response = repair_provider(request)
        if request.stage == 'review':
            return replace(response, response=response.response.replace('"approved": true', '"approved": false'))
        return response

    # When both reviews reject the article.
    with pytest.raises(PreparationError, match='independent_review_held'):
        _ = execute(run, reject)
    # Then no third review, approval receipt, or package exists.
    assert calls.count('review') == 2
    assert not list(run.directory.rglob('package'))
    assert not (tmp_path / 'contracts/reviews').exists()


def test_repair_cannot_change_media_identity(tmp_path: Path) -> None:
    # Given a writer attempting to change an approved image description.
    run = prepared_run(tmp_path)

    def change_alt(request: StageRequest) -> StageResponse:
        response = repair_provider(request)
        if request.stage == 'writing' and request.directory.name == 'text-repair':
            return replace(response, response=response.response.replace('테스트 장면 0', '다른 이미지'))
        return response

    # When the bounded repair is applied.
    with pytest.raises(PreparationError, match='text_repair_scope_changed'):
        _ = execute(run, change_alt)
    # Then changed media cannot enter a package.
    assert not list(run.directory.rglob('package'))


def test_repaired_replay_reuses_all_checkpoints(tmp_path: Path) -> None:
    # Given a completed repair under the same operation identity.
    run = prepared_run(tmp_path)
    first = execute(run, repair_provider)
    unused = FixtureProvider()
    # When the same run is replayed.
    replay = execute(run, unused)
    # Then no new model operation is dispatched.
    assert replay == first
    assert unused.calls == []


@pytest.mark.parametrize('failed', [name for name in CHECKS if name not in
    ('facts', 'reader_value', 'voice', 'originality', 'web_text_accessibility')])
def test_non_fact_failure_is_not_a_text_repair(tmp_path: Path, failed: str) -> None:
    # Given an otherwise successful review with a different failed gate.
    run = prepared_run(tmp_path)

    def reject(request: StageRequest) -> StageResponse:
        response = FixtureProvider()(request)
        response = replace(response, session_id=str(request.directory) + '-' + request.stage)
        if request.stage == 'review':
            source = response.response.replace('"approved": true', '"approved": false')
            source = source.replace(json.dumps(failed) + ': true', json.dumps(failed) + ': false')
            return replace(response, response=source.replace('"issues": []', '"issues": ["failed gate"]'))
        return response

    # When another gate fails.
    reason = 'media_enrichment_exhausted' if failed in ('rights', 'images', 'diversity') else 'independent_review_held'
    with pytest.raises(PreparationError, match=reason):
        _ = execute(run, reject)
    # Then this limited repair path is not used.
    assert not (run.directory / 'text-repair').exists()


@pytest.mark.parametrize('digest,approved,issues', [('wrong', False, ['error']),
                                                 ('expected', True, ['error']), ('expected', False, [])])
def test_repair_eligibility_rejects_invalid_binding_or_decision(
    digest: str, approved: bool, issues: list[str],
) -> None:
    source = json.dumps({'subject_sha256': digest, 'approved': approved, 'issues': issues,
                         'checks': {name: name != 'facts' for name in CHECKS}})
    eligible = text_repair_eligible(source, 'expected')
    assert not eligible


def test_repaired_writer_cannot_review_own_work(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)

    def same_session(request: StageRequest) -> StageResponse:
        response = repair_provider(request)
        if request.directory.name == 'text-repair' and request.stage in ('writing', 'review'):
            return replace(response, session_id='repair-shared-session')
        return response

    with pytest.raises(PreparationError, match='independent_review_session_required'):
        _ = execute(run, same_session)
    assert not list(run.directory.rglob('package'))


@pytest.mark.parametrize('failed', ['reader_value', 'voice', 'originality', 'web_text_accessibility'])
def test_final_editorial_defect_is_repaired_before_new_package_review(tmp_path: Path, failed: str) -> None:
    run = prepared_run(tmp_path)

    def repair_editorial(request: StageRequest) -> StageResponse:
        response = repair_provider(request)
        if request.stage == 'review' and request.directory.name != 'text-repair':
            return replace(response, response=response.response.replace('"facts": false', '"facts": true')
                .replace('"' + failed + '": true', '"' + failed + '": false'))
        return response

    assert execute(run, repair_editorial).is_dir()
    assert (run.directory / 'text-repair/review.receipt.json').is_file()
