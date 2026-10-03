from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path

import pytest

from tests.preparation_fixture import NOW
from tests.test_preparation_v2 import BODY, EditorialFixture, v2_run
from tistory_growth_os.artifacts.review_contract import ReviewCode
from tistory_growth_os.delivery.immediate_package import load_immediate_package
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute
from tistory_growth_os.preparation.shared_sources import SourceDocument, SourceReader


def test_sources_action_reuses_bodies_and_replays_without_new_calls(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture(('sources',))
    extra = 'https://example.org/additional'
    reader = SourceReader(run.directory / 'shared-sources')
    reader.remember(SourceDocument(extra, NOW.isoformat(), 'full_text', BODY,
        sha256(BODY.encode()).hexdigest(), sha256(b'extra').hexdigest(), ()))

    def provider(request: StageRequest) -> StageResponse:
        result = fixture(request)
        if request.stage == 'edit' and '"action": "sources"' in result.response:
            return replace(result, response=result.response.replace('"source_urls": []', '"source_urls": ' + json.dumps([extra])))
        return result

    package = execute(run, provider)
    assert extra in (package / 'evidence.md').read_text()
    replay = EditorialFixture()
    assert execute(run, replay) == package
    assert replay.calls == []


def test_media_action_replaces_once_then_attests(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture(('media',))
    package = execute(run, fixture)
    assert fixture.calls.count('media') == 2
    assert fixture.calls.count('writing') == 1
    assert load_immediate_package(tmp_path, package, NOW).review(NOW).code is ReviewCode.APPROVED


def test_topic_replacement_keeps_global_editor_budget(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture(('replace_topic',))

    def provider(request: StageRequest) -> StageResponse:
        result = fixture(request)
        if request.directory.name == 'candidate-02':
            return replace(result, response=result.response.replace('candidate-0', 'candidate-1'))
        return result

    package = execute(run, provider)
    assert package.parent.name == 'edit-turn-02'
    assert fixture.calls.count('discovery') == 2


def test_bad_initial_writing_goes_to_editor_not_terminal_failure(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture(('revise',))

    def provider(request: StageRequest) -> StageResponse:
        result = fixture(request)
        if request.stage == 'writing':
            return replace(result, response=result.response.replace('"category": "과학"', '"category": "미등록"'))
        if request.stage == 'edit':
            return replace(result, response=result.response.replace('미등록', '과학'))
        return result

    package = execute(run, provider)
    assert '과학' in (package / 'manifest.json').read_text()
    assert fixture.calls.count('writing') == 1


def test_selection_clock_is_real_decision_completion_and_package_still_loads(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture()
    times = [NOW]
    run = replace(run, clock=lambda: times[0])

    def provider(request: StageRequest) -> StageResponse:
        result = fixture(request)
        if request.stage == 'decision':
            times[0] = NOW + timedelta(minutes=10)
        return result

    package = execute(run, provider)
    manifest = (package / 'manifest.json').read_text()
    assert '"selected_at": "' + times[0].isoformat() in manifest
    assert load_immediate_package(tmp_path, package, times[0]).review(times[0]).code is ReviewCode.APPROVED
    assert NOW.isoformat() in (package / 'evidence.md').read_text()


def test_unknown_editor_attempt_is_not_retried(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture()
    directory = run.directory / 'edit-turn-01'
    directory.mkdir()
    _ = (directory / 'edit.attempt').write_text('uncertain')
    with pytest.raises(PreparationError, match='stage_attempt_uncertain'):
        _ = execute(run, fixture)
    assert 'edit' not in fixture.calls


def test_package_mutation_fails_replay(tmp_path: Path) -> None:
    run = v2_run(tmp_path)
    package = execute(run, EditorialFixture())
    _ = (package / 'article.html').write_text('tampered')
    with pytest.raises(PreparationError, match='final_package_changed'):
        _ = execute(run, EditorialFixture())


@pytest.mark.parametrize('change', ['unknown-version', 'remove-version', 'legacy-attempt'])
def test_workflow_migration_is_never_implicit(tmp_path: Path, change: str) -> None:
    run, provider = v2_run(tmp_path), EditorialFixture()
    if change == 'unknown-version':
        initial = run.directory / 'input.json'
        _ = initial.write_text(initial.read_text().replace('editorial-v2', 'editorial-v3'))
    elif change == 'remove-version':
        _ = execute(run, EditorialFixture())
        initial = run.directory / 'input.json'
        _ = initial.write_text(initial.read_text().replace('"workflow_version":"editorial-v2",', ''))
    else:
        _ = (run.directory / 'research.attempt').write_text('legacy')
    with pytest.raises(PreparationError, match='workflow_version'):
        _ = execute(run, provider)
    assert provider.calls == []
