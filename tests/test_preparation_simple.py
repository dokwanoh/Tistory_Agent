from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_preparation_v2 import EditorialFixture, v2_run
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.runner import execute
from tistory_growth_os.preparation.provider import StageRequest, StageResponse


def test_decision_delegates_original_bodies_to_host_without_duplicate_prompt_copy(tmp_path: Path) -> None:
    run, fixture = v2_run(tmp_path), EditorialFixture()
    initial = run.directory / 'input.json'
    _ = initial.write_text(initial.read_text().replace('editorial-v2', 'editorial-simple-v1'))

    def provider(request: StageRequest) -> StageResponse:
        if request.stage == 'decision':
            assert request.source_urls
            assert '"body":' not in request.prompt
        return fixture(request)

    package = execute(run, provider)
    assert (package / 'article.html').is_file()


def test_simple_selection_prepares_and_replays_without_opportunity(tmp_path: Path) -> None:
    # Given: readable sources and no measured demand or competition.
    run, provider = v2_run(tmp_path), EditorialFixture()
    initial = run.directory / 'input.json'
    _ = initial.write_text(initial.read_text().replace('editorial-v2', 'editorial-simple-v1'))
    # When: the fresh simple workflow prepares its package.
    package = execute(run, provider)
    # Then: it reaches writing and review without an opportunity call.
    assert provider.calls == ['discovery', 'decision', 'writing', 'media', 'edit']
    assert (package / 'article.html').is_file()
    assert not list(run.directory.glob('**/opportunity.attempt'))
    replay = EditorialFixture()
    assert execute(run, replay) == package
    assert replay.calls == []


def test_old_uncertain_opportunity_is_not_migrated_or_retried(tmp_path: Path) -> None:
    # Given: a previous v2 operation with an unfinished opportunity call.
    run, provider = v2_run(tmp_path), EditorialFixture()
    candidate = run.directory / 'candidate-01'
    candidate.mkdir()
    _ = (candidate / 'opportunity.attempt').write_text('uncertain')
    # When / Then: the old operation keeps its hold and does not call opportunity.
    with pytest.raises(PreparationError, match='stage_attempt_uncertain'):
        _ = execute(run, provider)
    assert provider.calls == ['discovery']


@pytest.mark.parametrize('version', ['editorial-v2', 'editorial-simple-v1'])
def test_started_workflow_cannot_be_relabelled(tmp_path: Path, version: str) -> None:
    run = v2_run(tmp_path)
    initial = run.directory / 'input.json'
    _ = initial.write_text(initial.read_text().replace('editorial-v2', version))
    _ = execute(run, EditorialFixture())
    other = 'editorial-simple-v1' if version == 'editorial-v2' else 'editorial-v2'
    _ = initial.write_text(initial.read_text().replace(version, other))
    provider = EditorialFixture()
    with pytest.raises((PreparationError, ValueError), match='changed|immutable'):
        _ = execute(run, provider)
    assert provider.calls == []


def test_cli_with_unavailable_metrics_still_prepares(tmp_path: Path) -> None:
    script = '''
import sys
import tistory_growth_os.preparation.__main__ as entry
from tests.test_preparation_v2 import EditorialFixture, v2_run
from tests.preparation_fixture import NOW
from pathlib import Path
run = v2_run(Path(sys.argv[1]))
(run.directory / 'input.json').unlink()
def missing():
    raise OSError('fixture feed unavailable')
entry.collect_live = missing
entry.codex_provider = EditorialFixture()
entry.utc_now = lambda: NOW
sys.argv = ['prepare', '--root', sys.argv[1], '--run-id', 'fixture-run', '--execute']
sys.exit(entry.main())
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True,
                            text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert 'local_package_reviewed' in result.stdout
    assert '"stage": "opportunity"' not in result.stderr
