import os
from pathlib import Path
import subprocess
import sys


def test_resume_cli_obeys_pause_before_package_or_browser(tmp_path: Path) -> None:
    # Given: an isolated project with STOP and no package, profile or credentials.
    root = Path(__file__).resolve().parents[1]
    runtime = tmp_path / '.artifacts' / 'native-runtime'
    runtime.mkdir(parents=True)
    _ = (runtime / 'STOP').write_text('paused', encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(root / 'src'), str(root / '.venv/lib/python3.11/site-packages'))))
    # When: the executable receives an explicit resume request.
    result = subprocess.run([sys.executable, '-m', 'tistory_growth_os.delivery.native_runner',
                             '--package', 'missing', '--authority', 'missing', '--execute', '--resume'],
                            cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    # Then: pause wins before package access, browser launch or database mutation.
    assert result.returncode == 2
    assert '"reason": "kill_switch"' in result.stdout
    assert not (tmp_path / 'browser-profile').exists()
    assert not (runtime / 'save-intents.sqlite3').exists()
