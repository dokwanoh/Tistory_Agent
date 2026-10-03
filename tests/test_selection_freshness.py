from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from tests.preparation_fixture import FixtureProvider, NOW
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.delivery.immediate_package import load_immediate_package
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute


@pytest.mark.parametrize('delayed_stage', ['writing', 'text_review', 'media'])
@pytest.mark.parametrize('expanded', [False, True])
def test_selected_issue_survives_production_age_and_replay(tmp_path: Path, delayed_stage: str, expanded: bool) -> None:
    # Given a fresh selected issue and a production delay beyond its first day.
    now = NOW
    fixture = FixtureProvider()
    run = replace(prepared_run(tmp_path), clock=lambda: now)

    def delayed(request: StageRequest) -> StageResponse:
        nonlocal now
        if expanded and request.stage == 'research' and request.directory == run.directory:
            return StageResponse('{"candidates":[],"policy_sources":[]}', 'empty-research', ('web_search',))
        if request.stage == delayed_stage:
            now = NOW + timedelta(hours=25)
        return fixture(request)

    # When preparation completes and the exact operation is replayed.
    package = execute(run, delayed)
    replay = FixtureProvider()
    repeated = execute(run, replay)
    loaded = load_immediate_package(tmp_path, package, now)

    # Then the same reviewed package remains usable without new provider calls.
    assert repeated == package
    assert replay.calls == []
    assert loaded.article.intent.valid_until > now


def test_selection_itself_cannot_choose_an_expired_issue(tmp_path: Path) -> None:
    # Given selection, rather than writing, takes the issue past 24 hours.
    now = NOW
    fixture = FixtureProvider()
    run = replace(prepared_run(tmp_path), clock=lambda: now)

    def late_selection(request: StageRequest) -> StageResponse:
        nonlocal now
        if request.stage == 'selection':
            now = NOW + timedelta(hours=24)
        return fixture(request)

    # When selection completes, then no writing or media may start.
    with pytest.raises(PreparationError, match='event_outside_24h'):
        _ = execute(run, late_selection)
    assert 'writing' not in fixture.calls
