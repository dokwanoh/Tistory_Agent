from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import subprocess
import sys
import json

import pytest

from tests.preparation_fixture import NOW, research_response
from tistory_growth_os.preparation.contracts import PreparationError, parse_research


def test_research_accepts_structured_search_and_rejection_evidence() -> None:
    # Given a qualified report with explicit investigation evidence,
    details = json.dumps({'search_notes': 'Official sources opened', 'rejected_leads': [
        {'lead': 'older event', 'reason': 'outside time window', 'source_urls': ['https://example.org/old']}]})
    source = research_response().removesuffix('}') + ',' + details.removeprefix('{')
    # When parsing the research boundary, then diagnostics do not discard qualified candidates.
    assert len(parse_research(source, NOW).candidates) == 5


def test_shortfall_requires_concrete_rejection_evidence() -> None:
    # Given an unexplained empty result, when parsing it, then the missing evidence is explicit.
    source = json.dumps({'candidates': [], 'policy_sources': [],
                         'search_notes': 'Search performed', 'rejected_leads': []})
    with pytest.raises(PreparationError, match='research_shortfall_undocumented'):
        _ = parse_research(source, NOW)


def test_runtime_clock_binds_source_checks_without_replacing_event_times() -> None:
    from tistory_growth_os.preparation.contracts import stamp_research
    source = research_response().replace('"checked_at": "' + NOW.isoformat() + '"',
                                         '"checked_at": "RUNTIME"')
    stamped = stamp_research(source, NOW)
    actual = parse_research(stamped, NOW)
    expected = parse_research(research_response(), NOW)
    assert [(c.candidate_id, c.event_at, c.urls) for c in actual.candidates] == [
        (c.candidate_id, c.event_at, c.urls) for c in expected.candidates]


def test_unknown_source_checks_are_not_repaired_as_success() -> None:
    from tistory_growth_os.preparation.contracts import stamp_research
    from tistory_growth_os.contracts.json_decode import JsonDecodeError
    source = research_response().replace('"checked_at": "' + NOW.isoformat() + '"',
                                         '"checked_at": "UNKNOWN"')
    with pytest.raises(JsonDecodeError):
        _ = parse_research(stamp_research(source, NOW), NOW)


def test_preparation_command_exists() -> None:
    # Given the installed domain package, when resolving the production entrypoint,
    # then a standalone preparation command exists.
    assert importlib.util.find_spec('tistory_growth_os.preparation') is not None


def test_dry_run_does_not_create_run_or_call_provider(tmp_path: Path) -> None:
    # Given an empty project, when planning a run, then no artifacts are created.
    result = subprocess.run([sys.executable, '-m', 'tistory_growth_os.preparation',
        '--root', str(tmp_path), '--run-id', 'dry-one'], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert 'dry_run' in result.stdout
    assert '"originals"' in result.stdout
    assert '"workflow_version": "editorial-simple-v1"' in result.stdout
    assert '"opportunity"' not in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_research_rejects_signal_time_without_sources() -> None:
    from tistory_growth_os.preparation.contracts import PreparationError, parse_research
    import pytest
    # Given no evidence-backed candidates, when accepting a provider response,
    # then the run is held rather than turning trend time into event time.
    with pytest.raises(PreparationError):
        _ = parse_research('{"candidates":[],"policy_sources":[]}', datetime.now(timezone.utc))
