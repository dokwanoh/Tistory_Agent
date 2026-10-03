from hashlib import sha256
import json
from pathlib import Path

import pytest

from tistory_growth_os.preparation.diagnostics import inspect_run


def test_missing_run_does_not_create_it(tmp_path: Path) -> None:
    report = inspect_run(tmp_path, 'manual-test')
    assert report.state == 'missing'
    assert report.retry_safe is False
    assert list(tmp_path.iterdir()) == []


def test_attempt_without_receipt_is_uncertain(tmp_path: Path) -> None:
    run = tmp_path / '.artifacts/preparation/manual-test'
    run.mkdir(parents=True)
    _ = (run / 'research.attempt').write_text('a' * 64)
    report = inspect_run(tmp_path, 'manual-test')
    assert report.stages[0].state == 'attempt_unresolved'
    assert report.retry_safe is False
    assert 'reconcile' in report.stages[0].action


def test_recorded_response_is_not_quality_or_publication_success(tmp_path: Path) -> None:
    run = tmp_path / '.artifacts/preparation/manual-test'
    run.mkdir(parents=True)
    response = '{"private_payload":"never show this"}'
    _ = (run / 'research.json').write_text(response)
    _ = (run / 'research.receipt.json').write_text(json.dumps({
        'request_sha256': 'a' * 64, 'response_sha256': sha256(response.encode()).hexdigest(),
        'session_id': 'secret-session', 'tool_kinds': ['web_search'],
    }))
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    report = inspect_run(tmp_path, 'manual-test')
    assert report.stages[0].state == 'response_recorded'
    assert report.publication_state == 'not_checked'
    assert 'secret' not in repr(report)
    assert 'private_payload' not in repr(report)
    assert before == {p.name: p.read_bytes() for p in run.iterdir()}
    _ = (run / 'research.json').write_text('{}')
    assert inspect_run(tmp_path, 'manual-test').stages[0].state == 'checkpoint_invalid'


@pytest.mark.parametrize('value', ['../escape', '/tmp/escape', 'a', 'manual/test'])
def test_invalid_identity_is_rejected(tmp_path: Path, value: str) -> None:
    assert inspect_run(tmp_path, value).state == 'invalid'


def test_malformed_receipt_and_symlink_fail_closed(tmp_path: Path) -> None:
    run = tmp_path / '.artifacts/preparation/manual-test'
    run.mkdir(parents=True)
    _ = (run / 'review.receipt.json').write_text('{bad')
    report = inspect_run(tmp_path, 'manual-test')
    assert report.stages[-1].state == 'checkpoint_invalid'
    (run / 'writing.json').symlink_to(run / 'review.receipt.json')
    assert next(stage for stage in inspect_run(tmp_path, 'manual-test').stages
                if stage.stage == 'writing').state == 'checkpoint_invalid'


def test_repair_stage_is_reported_without_overwriting_original(tmp_path: Path) -> None:
    run = tmp_path / '.artifacts/preparation/manual-test/text-repair'
    run.mkdir(parents=True)
    _ = (run / 'writing.attempt').write_text('a' * 64)
    report = inspect_run(tmp_path, 'manual-test')
    assert report.stages[-3].stage == 'text-repair/writing'
    assert report.stages[-3].state == 'attempt_unresolved'
