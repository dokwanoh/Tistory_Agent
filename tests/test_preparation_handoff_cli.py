import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_preparation_flow import prepared_run
from tests.test_preparation_publication import grant


def invoke(root: Path, *, approve: bool = True, outcome: int = 0) -> subprocess.CompletedProcess[str]:
    script = '''
import json, subprocess, sys
from pathlib import Path
import tistory_growth_os.preparation.__main__ as entry
import tistory_growth_os.preparation.publication as handoff
from tests.preparation_fixture import FixtureProvider, NOW
from tistory_growth_os.delivery.immediate_package import ImmediateAuthority, load_immediate_package
entry.codex_provider = FixtureProvider(approve=sys.argv.pop(1) == 'yes')
entry.utc_now = lambda: NOW
exit_code = int(sys.argv.pop(1))
actual_subprocess = subprocess.run
def publisher(command, **kwargs):
    if command[1:3] != ['-m', 'tistory_growth_os.delivery.immediate_runner']:
        return actual_subprocess(command, **kwargs)
    root = kwargs['cwd']
    package = load_immediate_package(root, root / command[4], NOW)
    assert command[5:7] == ['--execute', '--authority']
    authority = ImmediateAuthority(root / command[7], package)
    assert authority(package.article.intent, NOW) == ()
    with (root / 'publisher-called.jsonl').open('a') as stream:
        stream.write(json.dumps({'operation': package.article.intent.operation_id}) + '\\n')
    print(json.dumps({'state': 'verified' if exit_code == 0 else 'held', 'fixture': True}))
    return subprocess.CompletedProcess(command, exit_code)
handoff.subprocess.run = publisher
sys.exit(entry.main())
'''
    return subprocess.run([sys.executable, '-c', script, 'yes' if approve else 'no', str(outcome),
        '--root', str(root), '--run-id', 'fixture-run', '--execute',
        '--publish-grant', 'publication-grant.json'], capture_output=True, text=True, timeout=30, check=False)


@pytest.mark.parametrize('outcome', [0, 2])
def test_cli_preparation_automatically_invokes_publisher_and_propagates_result(tmp_path: Path, outcome: int) -> None:
    run = prepared_run(tmp_path)
    _ = grant(tmp_path)
    result = invoke(tmp_path, outcome=outcome)
    assert result.returncode == outcome, result.stderr
    assert 'publication_handoff' in result.stdout
    assert ('verified' if outcome == 0 else 'held') in result.stdout
    assert (tmp_path / 'publisher-called.jsonl').read_text().splitlines() == ['{"operation": "fixture-run"}']
    assert (run.directory / 'publication-authority.json').is_file()
    assert 'local_package_reviewed' not in result.stdout


def test_cli_rejected_quality_never_calls_publisher(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)
    _ = grant(tmp_path)
    result = invoke(tmp_path, approve=False)
    assert result.returncode == 2 and 'independent_review_held' in result.stderr
    assert not (tmp_path / 'publisher-called.jsonl').exists()
    assert not (run.directory / 'publication-authority.json').exists()


def test_cli_stop_prevents_even_model_calls(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)
    _ = grant(tmp_path)
    stop = tmp_path / '.artifacts/native-runtime/STOP'
    stop.parent.mkdir(parents=True)
    _ = stop.write_text('paused')
    result = invoke(tmp_path)
    assert result.returncode == 2 and 'kill_switch' in result.stderr
    assert not (run.directory / 'research.attempt').exists()
    assert not (tmp_path / 'publisher-called.jsonl').exists()
    assert stop.read_text() == 'paused'


def test_cli_dry_run_with_grant_does_not_read_or_publish(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, '-m', 'tistory_growth_os.preparation',
        '--root', str(tmp_path), '--run-id', 'dry-run', '--publish-grant', 'absent.json'],
        capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['external_write_count'] == 0
    assert list(tmp_path.iterdir()) == []


def test_local_preparation_dry_run_requires_no_browser_dependency(tmp_path: Path) -> None:
    script = "import sys, runpy; sys.modules['playwright'] = None; runpy.run_module('tistory_growth_os.preparation', run_name='__main__')"
    result = subprocess.run([sys.executable, '-c', script, '--root', str(tmp_path),
        '--run-id', 'without-browser'], capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'dry_run' in result.stdout and list(tmp_path.iterdir()) == []
