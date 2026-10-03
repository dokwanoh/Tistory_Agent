import subprocess
import sys
from pathlib import Path

from tests.preparation_fixture import NOW
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.delivery.immediate_package import load_immediate_package
from tistory_growth_os.artifacts.review_contract import ReviewCode


def invoke(root: Path, approve: bool) -> subprocess.CompletedProcess[str]:
    script = '''
import sys
import tistory_growth_os.preparation.__main__ as entry
from tests.preparation_fixture import FixtureProvider, NOW
entry.codex_provider = FixtureProvider(approve=sys.argv.pop(1) == 'yes')
entry.utc_now = lambda: NOW
sys.exit(entry.main())
'''
    return subprocess.run([sys.executable, '-c', script, 'yes' if approve else 'no',
        '--root', str(root), '--run-id', 'fixture-run', '--execute'],
        capture_output=True, text=True, timeout=30, check=False)


def test_cli_fixture_happy_replay_and_existing_publisher_contract(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)
    first = invoke(tmp_path, True)
    assert first.returncode == 0, first.stderr
    assert 'local_package_reviewed' in first.stdout
    package = load_immediate_package(tmp_path, run.directory / 'package', NOW)
    assert package.review(NOW).code is ReviewCode.APPROVED
    replay = invoke(tmp_path, False)
    assert replay.returncode == 0, replay.stderr
    assert not (run.directory / 'authority.json').exists()


def test_cli_fixture_rejection_is_nonzero_and_has_no_package(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)
    result = invoke(tmp_path, False)
    assert result.returncode == 2
    assert 'independent_review_held' in result.stderr
    assert not (run.directory / 'package').exists()
