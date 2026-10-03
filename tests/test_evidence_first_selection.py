from pathlib import Path
import json
import subprocess
import sys

import pytest

from tests.preparation_fixture import FixtureProvider, evidence_response
from tests.preparation_fixture import NOW, research_response
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.contracts import parse_research
from tistory_growth_os.preparation.evidence import enrich_candidate
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.runner import execute
from tests.test_opportunity_signals import feed


def test_final_selection_follows_verified_detail(tmp_path: Path) -> None:
    # Given a qualified candidate and independent stage providers.
    run, fixture = prepared_run(tmp_path), FixtureProvider()
    # When the real preparation pipeline executes.
    _ = execute(run, fixture)
    # Then detailed evidence precedes final selection.
    assert fixture.calls.index('evidence') < fixture.calls.index('selection')
    assert fixture.calls.index('opportunity') < fixture.calls.index('selection')


def test_unreadable_detail_never_reaches_selection(tmp_path: Path) -> None:
    # Given official detail remains unresolved after the bounded enrichment pass.
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def unavailable(request: StageRequest) -> StageResponse:
        if request.stage == 'evidence':
            directory = request.directory.parent if request.directory.name == 'evidence-enrichment' else request.directory
            identity = 'candidate-' + str(int(directory.name) - 1) if directory.name in ('02', '03') else 'candidate-0'
            return StageResponse(evidence_response().replace('confirmed', 'unknown').replace('candidate-0', identity),
                                 'unavailable-evidence', ('web_search',))
        return fixture(request)

    # When preparation attempts to qualify the source.
    with pytest.raises(PreparationError, match='source_candidates_exhausted'):
        _ = execute(run, unavailable)
    # Then neither final selection nor downstream production consumes calls.
    assert 'selection' not in fixture.calls
    assert 'writing' not in fixture.calls
    assert len(list(run.directory.rglob('source-rejected.json'))) == 3
    assert not (run.directory / 'source-candidates/04').exists()


def test_snippet_only_cannot_qualify_official_detail() -> None:
    candidate = parse_research(research_response(), NOW).candidates[0]
    snippet = evidence_response().replace('"full_text"', '"snippet"')
    with pytest.raises(PreparationError, match='essential_fact_primary_source_required'):
        _ = enrich_candidate(snippet, candidate, NOW)


def test_measured_demand_changes_which_topic_is_qualified(tmp_path: Path) -> None:
    # Given a second candidate tied to a measured trend and no invented volume for the others.
    run, fixture = prepared_run(tmp_path), FixtureProvider()
    _ = (run.directory / 'signals.rss').write_bytes(feed(5000))

    def measured(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if request.stage == 'opportunity':
            payload = json.dumps({'candidates': [{'candidate_id': f'candidate-{n}',
                'signal_query': '과학' if n == 1 else 'NONE', 'mapping_basis': 'Fixture exact issue match',
                'search_query': 'fixture question', 'limitations': 'Fixture search sample',
                'results': [{'url': f'https://example.org/{i}', 'answers_question': True,
                             'support': 'Fixture direct answer'} for i in range(3)]} for n in range(5)]})
            return StageResponse(payload, response.session_id, response.tool_kinds)
        if request.stage in ('evidence', 'selection'):
            return StageResponse(response.response.replace('candidate-0', 'candidate-1'),
                                 response.session_id, response.tool_kinds)
        return response

    # When measurements are routed through the production command's pipeline.
    package = execute(run, measured)
    # Then candidate1, not the original first candidate, is qualified and produces one package.
    assert package.is_dir()
    assert 'candidate-1' in (run.directory / 'selection.json').read_text()
    assert fixture.calls.count('writing') == 1


def test_cli_prepares_locally_with_fixture_external_services(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)
    script = ('import sys; from tests.preparation_fixture import FixtureProvider; '
              'import tistory_growth_os.preparation.__main__ as cli; '
              'from tests.preparation_fixture import NOW; cli.utc_now=lambda: NOW; '
              'cli.codex_provider=FixtureProvider(); sys.exit(cli.main())')
    result = subprocess.run([sys.executable, '-c', script, '--root', str(tmp_path),
        '--run-id', run.run_id, '--execute'], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert 'local_package_reviewed' in result.stdout
    assert '"external_blog_write_count": 0' in result.stdout
    assert (run.directory / 'opportunity-comparison.json').is_file()


def test_legacy_selection_is_preserved_without_new_calls(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()
    _ = (run.directory / 'selection.attempt').write_text('historical-attempt')
    with pytest.raises(PreparationError, match='selection_workflow_changed'):
        _ = execute(run, fixture)
    assert fixture.calls == []
