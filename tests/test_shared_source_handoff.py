from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
from datetime import timedelta

import pytest

from tests.preparation_fixture import FixtureProvider, NOW, research_response
from tests.test_preparation_flow import prepared_run
from tests.test_preparation_repair import repair_provider
from tistory_growth_os.contracts.json_decode import parse_json
from tistory_growth_os.domain.common import Fields, array, as_object, text
from tistory_growth_os.preparation import provider as adapter
from tistory_growth_os.preparation.contracts import PreparationError, parse_research
from tistory_growth_os.preparation.enrichment import TextContext, final_evidence_enrichment, verified_detail
from tistory_growth_os.preparation.provider import StageRequest, StageResponse, codex_provider
from tistory_growth_os.preparation.shared_sources import extract_document
from tistory_growth_os.preparation.source_access import bind_detail_sources, operation_root
from tistory_growth_os.preparation.storage import StageStore
from tistory_growth_os.preparation.package import evidence_checked_at
from tistory_growth_os.preparation.runner import execute
from tistory_growth_os.preparation.evidence import enrich_candidate


def captured(url: str) -> str:
    doc = extract_document(url, ('<main>' + '실제 확인된 안내 본문. ' * 40 + '</main>').encode(), NOW)
    return json.dumps({'documents': [asdict(doc)], 'uncollected_urls': []}, ensure_ascii=False)


@pytest.mark.parametrize('stage', ['evidence', 'text_review', 'review'])
def test_grounded_stages_disable_model_web_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    fixture = FixtureProvider()
    request = StageRequest('evidence', 'source data', tmp_path)
    if stage == 'text_review':
        request = replace(request, stage='text_review')
    if stage == 'review':
        request = replace(request, stage='review')
    sources = captured('https://example.org/guide')
    def collect(_directory: Path, _prompt: str, _urls: tuple[str, ...]) -> str:
        return sources

    monkeypatch.setattr(adapter, 'collect_context', collect)
    response = fixture(StageRequest('evidence', '', tmp_path)).response if stage == 'evidence' else '{}'

    def run(argv: list[str], *, input: str, text: bool, capture_output: bool,
            check: bool, timeout: int) -> subprocess.CompletedProcess[str]:
        assert '--search' not in argv
        assert 'web_search="disabled"' in argv
        assert sources in input
        assert text and capture_output and not check and timeout == 900
        events = '\n'.join(json.dumps(event) for event in (
            {'type': 'thread.started', 'thread_id': 'independent'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': response}},
            {'type': 'turn.completed'}))
        return subprocess.CompletedProcess(argv, 0, events, '')

    monkeypatch.setattr(subprocess, 'run', run)
    result = codex_provider(request)
    assert not result.tool_kinds
    assert result.sources == sources


def test_unfetched_full_text_assertion_cannot_become_verified_evidence(tmp_path: Path) -> None:
    fixture = FixtureProvider()
    raw = fixture(StageRequest('evidence', '', tmp_path)).response
    bound = bind_detail_sources(raw, captured('https://unrelated.example/other'))
    fields = Fields(as_object(parse_json(bound), ''), '', ())
    assert all(text(Fields(as_object(item, ''), '', ()), 'access') == 'unavailable'
               for item in array(fields, 'sources', True))
    assert all(text(Fields(as_object(item, ''), '', ()), 'checked_at') == 'UNCOLLECTED'
               for item in array(fields, 'sources', True))
    candidate = parse_research(research_response(), NOW).candidates[0]
    with pytest.raises(PreparationError, match='essential_fact_primary_source_required'):
        _ = enrich_candidate(bound, candidate, NOW)


def test_snapshot_is_bound_to_receipt_and_carried_to_writing(tmp_path: Path) -> None:
    fixture = FixtureProvider()
    candidate = parse_research(research_response(), NOW).candidates[0]
    sources = captured(candidate.urls[0])

    def provider(request: StageRequest) -> StageResponse:
        response = fixture(request)
        return replace(response, sources=sources)

    store = StageStore(tmp_path, provider)
    request = StageRequest('evidence', 'fixture', tmp_path)
    _ = store.run(request)
    result = verified_detail(store, TextContext(candidate, lambda: NOW, frozenset()))
    assert result.evidence.get('source_snapshots') is not None
    assert evidence_checked_at(result, NOW + timedelta(hours=23)) == NOW
    with pytest.raises(PreparationError, match='source_clock_invalid'):
        _ = evidence_checked_at(result, NOW - timedelta(seconds=1))
    _ = store.run(request)
    assert fixture.calls == ['evidence']
    (tmp_path / 'evidence.sources.json').unlink()
    with pytest.raises(PreparationError, match='source_snapshot_changed'):
        _ = store.run(request)


def test_candidate_reselection_and_nested_repair_share_operation_cache(tmp_path: Path) -> None:
    _ = (tmp_path / 'input.json').write_text('{}')
    nested = tmp_path / 'source-reselection/pre-media-repair'
    nested.mkdir(parents=True)
    _ = (nested.parent / 'input.json').write_text('{}')
    assert operation_root(nested) == tmp_path


def test_final_supplement_preserves_old_source_time_but_accepts_new_collection(tmp_path: Path) -> None:
    clock = [NOW]
    run = replace(prepared_run(tmp_path), clock=lambda: clock[0])
    candidate = parse_research(research_response(), NOW).candidates[0]

    def provider(request: StageRequest) -> StageResponse:
        response = repair_provider(request)
        if request.stage == 'review' and request.directory.name != 'text-repair':
            clock[0] = NOW + timedelta(hours=1)
        if request.stage == 'evidence' and request.directory.name == 'text-repair':
            docs = [extract_document(url, ('<main>' + '추가 확인된 자료. ' * 50 + '</main>').encode(),
                                     NOW if index == 0 else clock[0])
                    for index, url in enumerate(candidate.urls)]
            return replace(response, sources=json.dumps({'documents': [asdict(doc) for doc in docs]}))
        return response

    package = execute(run, provider)
    manifest = Fields(as_object(parse_json((package / 'manifest.json').read_text()), ''), '', ())
    assert text(manifest, 'evidence_checked_at') == NOW.isoformat()
    unused = FixtureProvider()
    assert execute(run, unused) == package
    assert not unused.calls


@pytest.mark.parametrize('legacy_checkpoint', ['writing.attempt', 'writing.receipt.json'])
def test_legacy_final_repair_cannot_dispatch_a_new_evidence_stage(tmp_path: Path, legacy_checkpoint: str) -> None:
    candidate = parse_research(research_response(), NOW).candidates[0]
    fixture = FixtureProvider()
    _ = (tmp_path / legacy_checkpoint).write_text('{}')
    store = StageStore(tmp_path, fixture)
    with pytest.raises(PreparationError, match='source_workflow_changed'):
        _ = final_evidence_enrichment(store, TextContext(candidate, lambda: NOW, frozenset()),
                                     json.dumps({'checks': {'facts': False}}))
    assert not fixture.calls
    assert not (tmp_path / 'evidence.attempt').exists()
