from pathlib import Path
import subprocess
import sys

from tistory_growth_os.contracts.json_decode import parse_json
from tistory_growth_os.domain.common import as_object


def test_fresh_cli_reaches_package_without_fixed_seoul_pool(tmp_path: Path) -> None:
    # Given fresh intake, a non-Seoul candidate and an unavailable fixed-feed adapter.
    script = '''
import sys
from pathlib import Path
import tistory_growth_os.preparation.source_capture as capture
from tistory_growth_os.preparation.contracts import PreparationError
def unavailable(*args):
    raise PreparationError('fixed_feed_must_not_gate_discovery')
capture.capture_sources = unavailable
import tistory_growth_os.preparation.__main__ as entry
from tests.preparation_fixture import NOW
from tests.test_preparation_v2 import EditorialFixture, BODY, URL, GUIDE
from tistory_growth_os.preparation.shared_sources import SourceDocument, SourceReader
from tistory_growth_os.preparation.v2_prompts import POLICY_URLS
from hashlib import sha256
root = Path(sys.argv[sys.argv.index('--root') + 1])
reader = SourceReader(root / '.artifacts/preparation/fixture-run/shared-sources')
for url in (URL, GUIDE, *POLICY_URLS):
    reader.remember(SourceDocument(url, NOW.isoformat(), 'full_text', BODY,
        sha256(BODY.encode()).hexdigest(), sha256(b'fixture').hexdigest(), ()))
entry.codex_provider = EditorialFixture()
entry.utc_now = lambda: NOW
entry.collect_live = lambda: b'<rss><channel/></rss>'
sys.exit(entry.main())
'''
    # When the actual CLI creates its input and executes the complete local flow.
    result = subprocess.run([sys.executable, '-c', script, '--root', str(tmp_path),
        '--run-id', 'fixture-run', '--execute'], capture_output=True, text=True,
        check=False, timeout=30)
    # Then it accepts independently qualified non-Seoul evidence, without external publication.
    assert result.returncode == 0, result.stderr
    directory = tmp_path / '.artifacts/preparation/fixture-run'
    initial = as_object(parse_json((directory / 'input.json').read_text()), '')
    assert initial.get('source_pool_sha256') is None
    assert 'local_package_reviewed' in result.stdout
    assert 'https://example.org/official' in next(directory.glob('edit-turn-*/package/article.html')).read_text()
    assert not (directory / 'publication-authority.json').exists()
