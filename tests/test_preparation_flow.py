from datetime import timedelta
import json
from pathlib import Path

import pytest

from tests.preparation_fixture import FixtureProvider, NOW, research_response
from tistory_growth_os.preparation.contracts import PreparationError, parse_research
from tistory_growth_os.preparation.runner import PreparationRun, execute, recorded_research
from tistory_growth_os.preparation.storage import StageStore
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.package import promote
from tistory_growth_os.preparation.storage import media_files
from tests.preparation_fixture import media_response


def prepared_run(root: Path) -> PreparationRun:
    directory = root / '.artifacts/preparation/fixture-run'
    directory.mkdir(parents=True)
    _ = (directory / 'input.json').write_text(json.dumps({'run_id': 'fixture-run',
        'cutoff': NOW.isoformat(), 'signals': 'fixture', 'history': 'fixture history'}))
    return PreparationRun(root, directory, 'fixture-run', lambda: NOW)


def test_full_preparation_outputs_native_package(tmp_path: Path) -> None:
    run, provider = prepared_run(tmp_path), FixtureProvider()
    package = execute(run, provider)
    assert package.name == 'package'
    assert provider.calls == ['research', 'opportunity', 'evidence', 'selection', 'writing', 'text_review', 'media', 'review']
    assert (package / 'manifest.json').is_file()
    assert len(list((tmp_path / 'contracts/reviews').glob('*.json'))) == 1
    assert 'example.org' in (package / 'article.html').read_text()
    assert '관련 근거 자세히 보기' not in (package / 'article.html').read_text()
    assert 'word-break:keep-all;overflow-wrap:anywhere' in (package / 'article.html').read_text()
    assert 'Fixture-only source' not in (package / 'article.html').read_text()
    assert (package / 'article.html').read_text().count('href="https://example.org/official"') == 4
    assert 'Runtime media evidence' in (package / 'evidence.md').read_text()
    assert 'Taxonomy contract' in (package / 'evidence.md').read_text()
    assert 'media/01.jpg SHA-256' in (package / 'quality.md').read_text()


def test_quality_rejection_never_promotes(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)
    with pytest.raises(PreparationError, match='independent_review_held'):
        _ = execute(run, FixtureProvider(approve=False))
    assert not (run.directory / 'package').exists()
    assert not (tmp_path / 'contracts/reviews').exists()


def test_completed_replay_makes_no_provider_calls(tmp_path: Path) -> None:
    run, original = prepared_run(tmp_path), FixtureProvider()
    first = execute(run, original)
    replacement = FixtureProvider()
    second = execute(run, replacement)
    assert first == second
    assert replacement.calls == []


def test_changed_checkpoint_is_not_reused(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)
    _ = execute(run, FixtureProvider())
    _ = (run.directory / 'writing.json').write_text('{}')
    with pytest.raises(PreparationError, match='checkpoint_changed'):
        _ = execute(run, FixtureProvider())


def test_ambiguous_attempt_is_not_retried(tmp_path: Path) -> None:
    _ = (tmp_path / 'research.attempt').write_text('uncertain')
    provider = FixtureProvider()
    with pytest.raises(PreparationError, match='stage_attempt_uncertain'):
        _ = StageStore(tmp_path, provider).run(StageRequest('research', 'fixture', tmp_path))
    assert provider.calls == []


def test_stale_sources_cannot_reenter() -> None:
    with pytest.raises(PreparationError, match='event_outside_24h'):
        _ = parse_research(research_response(), NOW + timedelta(hours=23))


def test_package_edit_invalidates_replay(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)
    package = execute(run, FixtureProvider())
    _ = (package / 'article.html').write_text('changed')
    with pytest.raises(PreparationError, match='final_package_changed'):
        _ = execute(run, FixtureProvider())


def test_unknown_media_origin_is_blocked(tmp_path: Path) -> None:
    source = media_response(tmp_path).replace('generated', 'unlicensed')
    with pytest.raises(PreparationError, match='media_origin_invalid'):
        _ = media_files(tmp_path, source)


def test_official_media_without_rights_url_is_blocked(tmp_path: Path) -> None:
    source = media_response(tmp_path).replace('"origin": "generated"', '"origin": "official"')
    with pytest.raises(PreparationError, match='official_provenance_required'):
        _ = media_files(tmp_path, source)


def test_duplicate_media_bytes_are_blocked(tmp_path: Path) -> None:
    source = media_response(tmp_path)
    _ = (tmp_path / 'media/02.jpg').write_bytes((tmp_path / 'media/01.jpg').read_bytes())
    with pytest.raises(PreparationError, match='four_distinct_images_required'):
        _ = media_files(tmp_path, source)


def test_future_event_is_blocked() -> None:
    with pytest.raises(PreparationError, match='event_outside_24h'):
        _ = parse_research(research_response(), NOW - timedelta(hours=2))


def test_claim_source_mismatch_is_blocked() -> None:
    source = research_response().replace('"source_url": "https://example.org/official"',
                                         '"source_url": "https://other.example/unknown"')
    with pytest.raises(PreparationError, match='claim_source_missing'):
        _ = parse_research(source, NOW)


def test_approval_package_rejects_unreviewed_symlink(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)
    package = execute(run, FixtureProvider())
    (run.directory / 'inspection/unreviewed.txt').symlink_to(package / 'article.html')
    with pytest.raises(PreparationError, match='package_symlink_forbidden'):
        _ = promote(run.directory, 'unused')


def test_jpeg_markers_do_not_prove_decodable_image(tmp_path: Path) -> None:
    source = media_response(tmp_path)
    _ = (tmp_path / 'media/01.jpg').write_bytes(b'\xff\xd8\xff' + b'x' * 1200 + b'\xff\xd9')
    with pytest.raises(PreparationError, match='jpeg_decode_failed'):
        _ = media_files(tmp_path, source)


def test_writer_session_cannot_approve_own_package(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def same_session(request: StageRequest) -> StageResponse:
        response = fixture(request)
        session = 'same-session' if request.stage in ('writing', 'review') else response.session_id
        return StageResponse(response.response, session, response.tool_kinds)

    with pytest.raises(PreparationError, match='independent_review_session_required'):
        _ = execute(run, same_session)
    assert not (run.directory / 'package').exists()


@pytest.mark.parametrize('tool_kinds', [(), ('image_generation',)])
def test_generated_assets_require_generation_tool_evidence(tmp_path: Path, tool_kinds: tuple[str, ...]) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def no_generation(request: StageRequest) -> StageResponse:
        response = fixture(request)
        if request.stage == 'media':
            return StageResponse(media_response(request.directory), response.session_id, tool_kinds)
        return StageResponse(response.response, response.session_id, ())

    with pytest.raises(PreparationError, match='generation_tool_evidence_required'):
        _ = execute(run, no_generation)


def test_empty_research_gets_one_bounded_broader_search(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()

    def empty_first(request: StageRequest) -> StageResponse:
        if request.stage == 'research' and request.directory == run.directory:
            return StageResponse('{"candidates":[],"policy_sources":[]}', 'first-research', ('web_search',))
        return fixture(request)

    assert execute(run, empty_first).is_dir()
    assert (run.directory / 'research-expansion/research.receipt.json').exists()


def test_receipt_preserves_repeated_web_search_calls(tmp_path: Path) -> None:
    def repeated(request: StageRequest) -> StageResponse:
        return StageResponse(research_response(), request.stage, ('web_search', 'web_search'))

    store = StageStore(tmp_path, repeated)
    _ = store.run(StageRequest('research', 'fixture', tmp_path))
    assert store.receipt('research').tool_kinds == ('web_search', 'web_search')


def test_research_runtime_timestamp_is_frozen_on_replay(tmp_path: Path) -> None:
    fixture = FixtureProvider()

    def runtime_source(request: StageRequest) -> StageResponse:
        response = fixture(request)
        return StageResponse(response.response.replace('"checked_at": "' + NOW.isoformat() + '"',
            '"checked_at": "RUNTIME"'), response.session_id, response.tool_kinds)

    store = StageStore(tmp_path, runtime_source)
    request = StageRequest('research', 'fixture', tmp_path)
    first = recorded_research(store, request, lambda: NOW)
    replay = recorded_research(store, request, lambda: NOW + timedelta(hours=1))
    assert first == replay
    assert fixture.calls == ['research']
    assert len(parse_research(replay, NOW).candidates) == 5


def test_prior_research_leads_are_bounded_and_never_include_package_reviews(tmp_path: Path) -> None:
    from tistory_growth_os.preparation.storage import prior_research_leads
    import os
    for index in range(4):
        directory = tmp_path / '.artifacts/preparation' / f'prior-{index}'
        directory.mkdir(parents=True)
        path = directory / 'research.json'
        _ = path.write_text(research_response().replace('candidate-', f'lead-{index}-'))
        os.utime(path, (index + 1, index + 1))
        _ = (directory / 'review.json').write_text('private-review-must-not-be-input')
    source = prior_research_leads(tmp_path)
    assert 'lead-3-0' in source and 'lead-2-0' in source
    assert 'lead-1-0' not in source and 'lead-0-0' not in source
    assert 'private-review-must-not-be-input' not in source


def test_prior_research_rejects_symlinked_parent(tmp_path: Path) -> None:
    from tistory_growth_os.preparation.storage import prior_research_leads
    from tistory_growth_os.artifacts.layout import ArtifactWriteError
    outside = tmp_path / 'outside'
    outside.mkdir()
    _ = (outside / 'research.json').write_text(research_response())
    root = tmp_path / 'project'
    directory = root / '.artifacts/preparation'
    directory.mkdir(parents=True)
    (directory / 'linked-run').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactWriteError, match='symlink'):
        _ = prior_research_leads(root)


def test_history_includes_scheduled_and_publish_manifest_packages(tmp_path: Path) -> None:
    from tistory_growth_os.preparation.storage import history_snapshot
    for relative in ('fasttrack/a/manifest.json', 'scheduled/2026-09-20/1900/manifest.json',
                     'fasttrack/older/publish-manifest.json'):
        path = tmp_path / 'content' / relative
        path.parent.mkdir(parents=True)
        _ = path.write_text(relative)
    history = history_snapshot(tmp_path)
    assert '1900/manifest.json' in history and 'publish-manifest.json' in history
