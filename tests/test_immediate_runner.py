from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys

from tests.test_immediate_package import immediate_package_fixture


def cli(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src') + os.pathsep + str(
        Path(__file__).resolve().parents[1] / '.venv/lib/python3.11/site-packages')
    return subprocess.run([sys.executable, '-m', 'tistory_growth_os.delivery.immediate_runner', *arguments],
        cwd=root, env=environment, capture_output=True, text=True, timeout=30, check=False)


def test_cli_help_bad_input_and_stop_do_not_start_browser(tmp_path: Path) -> None:
    result = cli(tmp_path, '--help')
    assert result.returncode == 0
    assert '--recover' in result.stdout and '--execute' in result.stdout
    bad = cli(tmp_path, '--package', 'missing')
    assert bad.returncode == 2 and 'held' in bad.stdout
    runtime = tmp_path / '.artifacts' / 'native-runtime'
    runtime.mkdir(parents=True)
    _ = (runtime / 'STOP').write_text('fixture paused')
    stopped = cli(tmp_path, '--package', 'missing', '--execute')
    assert stopped.returncode == 2 and 'kill_switch' in stopped.stdout
    assert not (tmp_path / 'browser-profile').exists()


def test_cli_default_dry_run_reports_missing_review_without_browser(tmp_path: Path) -> None:
    folder = immediate_package_fixture(tmp_path)
    manifest = folder / 'manifest.json'
    now = datetime.now(timezone.utc)
    source = manifest.read_text()
    for clock in ('01:00:00', '14:00:00'):
        source = source.replace('2030-01-01T' + clock + '+09:00', now.isoformat())
    source = source.replace('2030-01-01T19:00:00+09:00', (now + timedelta(hours=1)).isoformat())
    _ = manifest.write_text(source)
    result = cli(tmp_path, '--package', 'content/pilot')
    assert result.returncode == 2
    assert 'dry_run' in result.stdout and 'REVIEW_REQUIRED' in result.stdout
    assert '"browser_calls": 0' in result.stdout and '"external_write_count": 0' in result.stdout
    assert not (tmp_path / 'browser-profile').exists()
