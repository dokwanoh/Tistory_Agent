from dataclasses import replace
from pathlib import Path

import pytest

from tests.test_immediate_execution import Surface, intent_fixture
from tistory_growth_os.delivery.editor_checkpoint import record_editor
from tistory_growth_os.delivery.editor_correction import OwnedEditor
from tistory_growth_os.delivery.immediate_execution import ImmediateExecutor, ImmediateJournal
from tistory_growth_os.delivery.native_article_source import NativeAlt
from tistory_growth_os.delivery.playwright_observation import UploadedAsset
from tistory_growth_os.delivery.reservation_execution import ExecutionState
from tistory_growth_os.domain.ids import MediaId


@pytest.mark.parametrize('case', ['no_claim', 'different_digest', 'save_started', 'uncertain_save'])
def test_resume_preserves_save_boundary(tmp_path: Path, case: str) -> None:
    journal, request = ImmediateJournal(tmp_path / 'journal.sqlite3'), intent_fixture()
    surface = Surface('valid')
    if case != 'no_claim':
        assert journal.saves.claim(request.key, request.package_digest)
    if case == 'different_digest':
        request = replace(request, package_digest='c' * 64)
    if case == 'save_started':
        journal.start(request, surface.now())
    if case == 'uncertain_save':
        journal.start(request, surface.now())
        assert Surface('unknown').save(request) is None

    result = ImmediateExecutor(journal, surface).run(request, dry_run=False, resume_editor=True)

    assert result.execution.state is ExecutionState.HELD
    assert surface.saves == surface.prepares == 0


def test_checkpoint_keeps_hashes_not_signed_source_values(tmp_path: Path) -> None:
    uploads = tuple(UploadedAsset(MediaId(str(i)), f'https://cdn.test/{i}.jpg?signature=secret-{i}',
                                  f'{i}.jpg') for i in range(4))
    editor = OwnedEditor('제목', 'native source with signature=secret-0', 'a' * 64,
                        tuple(NativeAlt(f'{i}.jpg', f'사진 {i}') for i in range(4)), uploads, '<p>본문</p>')
    path = tmp_path / 'editor.json'

    record_editor(path, 'b' * 64, editor)

    assert 'secret-' not in path.read_text()
    assert 'cdn.test' not in path.read_text()
    assert 'source_sha256' in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
