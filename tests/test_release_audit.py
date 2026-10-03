from pathlib import Path
import subprocess

from tistory_growth_os.release_audit import scan_bytes, scan_repository


def test_scanner_detects_private_targets_without_echoing_values() -> None:
    payload = ('https://' + 'private-owner' + '.tistory.com /Users/' + 'private-user/project').encode()
    findings = scan_bytes('sample.txt', payload, ())
    assert {finding.rule for finding in findings} == {'blog_identity', 'home_directory'}
    assert 'private-owner' not in repr(findings)
    assert 'private-user' not in repr(findings)


def test_scanner_accepts_synthetic_example() -> None:
    payload = b'https://example.tistory.com https://notice.tistory.com/2664 owner@example.test'
    assert scan_bytes('sample.txt', payload, ()) == ()


def test_scanner_honors_private_terms() -> None:
    assert scan_bytes('sample.txt', b'PRIVATE-BRAND', ('private-brand',))[0].rule == 'private_term'


def test_scanner_catches_tracked_local_files(tmp_path: Path) -> None:
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    local = tmp_path / '.local'
    local.mkdir()
    (local / 'profile.json').write_text('{}')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.local/profile.json'], check=True)
    findings = scan_repository(tmp_path, ())
    assert any(f.rule == 'private_path' for f in findings)


def test_scanner_inspects_index_even_after_worktree_is_cleaned(tmp_path: Path) -> None:
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    target = tmp_path / 'notes.txt'
    target.write_text('sensitive-marker')
    subprocess.run(['git', '-C', str(tmp_path), 'add', 'notes.txt'], check=True)
    target.write_text('clean')
    findings = scan_repository(tmp_path, ('sensitive-marker',))
    assert any(f.rule == 'private_term' for f in findings)
