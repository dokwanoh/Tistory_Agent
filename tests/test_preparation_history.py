from pathlib import Path

from tistory_growth_os.preparation.storage import history_snapshot


def test_history_when_package_promoted_outside_content_includes_it(tmp_path: Path) -> None:
    package = tmp_path / '.artifacts/preparation/manual-proof/text-repair/package'
    package.mkdir(parents=True)
    _ = (package / 'manifest.json').write_text('{"title":"newly prepared topic"}')
    assert 'newly prepared topic' in history_snapshot(tmp_path)


def test_history_when_inspection_is_unapproved_excludes_it(tmp_path: Path) -> None:
    package = tmp_path / '.artifacts/preparation/manual-proof/inspection'
    package.mkdir(parents=True)
    _ = (package / 'manifest.json').write_text('{"title":"unapproved topic"}')
    assert 'unapproved topic' not in history_snapshot(tmp_path)
