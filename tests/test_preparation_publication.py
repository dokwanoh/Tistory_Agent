from datetime import timedelta
import json
from pathlib import Path

import pytest

from tests.preparation_fixture import FixtureProvider, NOW
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.runner import execute
from tistory_growth_os.delivery.immediate_package import ImmediateAuthority, load_immediate_package
from tistory_growth_os.preparation.publication import PublicationGrant


def grant(root: Path, *, run_id: str = 'fixture-run', expired: bool = False) -> Path:
    path = root / 'publication-grant.json'
    _ = path.write_text(json.dumps({'scope': 'one-preparation-native-immediate',
        'approval_id': 'fixture-owner', 'run_id': run_id,
        'approved_at': (NOW - timedelta(hours=1)).isoformat(),
        'valid_until': (NOW + timedelta(hours=-1 if expired else 1)).isoformat()}))
    return path


def test_grant_binds_only_reviewed_package(tmp_path: Path) -> None:
    # Given: completed independent preparation and a one-run owner grant.
    run = prepared_run(tmp_path)
    package_path = execute(run, FixtureProvider())
    approval = PublicationGrant.read(run, grant(tmp_path))
    # When: completion binds the publication grant to the actual reviewed bytes.
    authority_path = approval.bind(package_path)
    # Then: the unchanged existing publisher accepts exact scope and review.
    package = load_immediate_package(tmp_path, package_path, NOW)
    assert ImmediateAuthority(authority_path, package)(package.article.intent, NOW) == ()
    assert approval.bind(package_path) == authority_path


@pytest.mark.parametrize('kind', ['expired', 'wrong_run', 'stop'])
def test_publication_preflight_holds_invalid_authority(tmp_path: Path, kind: str) -> None:
    # Given: a wrong-run/expired grant or an active runtime STOP.
    run = prepared_run(tmp_path)
    path = grant(tmp_path, run_id='other-run' if kind == 'wrong_run' else run.run_id,
                 expired=kind == 'expired')
    if kind == 'stop':
        stop = tmp_path / '.artifacts/native-runtime/STOP'
        stop.parent.mkdir(parents=True)
        _ = stop.write_text('paused')
    # When / Then: no binding, preparation or browser work can start.
    with pytest.raises(PreparationError):
        _ = PublicationGrant.read(run, path)
    assert not (run.directory / 'publication-authority.json').exists()


def test_review_removed_between_preparation_and_handoff_holds(tmp_path: Path) -> None:
    # Given: an otherwise ready package whose separate review is now denied.
    run = prepared_run(tmp_path)
    package = execute(run, FixtureProvider())
    for review in (tmp_path / 'contracts/reviews').glob('*.json'):
        _ = review.write_text(review.read_text().replace('"approved"', '"rejected"'))
    approval = PublicationGrant.read(run, grant(tmp_path))
    # When / Then: local completion cannot substitute for current independent review.
    with pytest.raises(PreparationError):
        _ = approval.bind(package)
    assert not (run.directory / 'publication-authority.json').exists()


@pytest.mark.parametrize('change', ['stop', 'grant', 'package'])
def test_handoff_rechecks_changes_after_preflight(tmp_path: Path, change: str) -> None:
    run = prepared_run(tmp_path)
    package = execute(run, FixtureProvider())
    path = grant(tmp_path)
    approval = PublicationGrant.read(run, path)
    if change == 'stop':
        stop = tmp_path / '.artifacts/native-runtime/STOP'
        stop.parent.mkdir(parents=True)
        _ = stop.write_text('paused during preparation')
    elif change == 'grant':
        _ = path.write_text(path.read_text().replace('fixture-owner', 'changed-owner'))
    else:
        _ = (package / 'evidence.md').write_text('altered after review')
    with pytest.raises(PreparationError):
        _ = approval.bind(package)
    assert not (run.directory / 'publication-authority.json').exists()


def test_changed_package_cannot_rebind_existing_authority(tmp_path: Path) -> None:
    run = prepared_run(tmp_path)
    package_path = execute(run, FixtureProvider())
    approval = PublicationGrant.read(run, grant(tmp_path))
    authority = approval.bind(package_path)
    original = authority.read_bytes()
    _ = (package_path / 'quality.md').write_text('changed')
    with pytest.raises(PreparationError):
        _ = approval.bind(package_path)
    assert authority.read_bytes() == original


def test_real_publisher_subprocess_honors_stop_created_at_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
) -> None:
    run = prepared_run(tmp_path)
    package = execute(run, FixtureProvider())
    approval = PublicationGrant.read(run, grant(tmp_path))
    original_bind = PublicationGrant.bind

    def stop_after_binding(self: PublicationGrant, folder: Path) -> Path:
        authority = original_bind(self, folder)
        stop = tmp_path / '.artifacts/native-runtime/STOP'
        stop.parent.mkdir(parents=True)
        _ = stop.write_text('stopped at process boundary')
        return authority

    monkeypatch.setattr(PublicationGrant, 'bind', stop_after_binding)
    result = approval.publish(package)
    output = capfd.readouterr().out
    assert result == 2 and 'publication_handoff' in output and 'kill_switch' in output
    assert not (tmp_path / 'browser-profile').exists()
    assert not (tmp_path / '.artifacts/native-runtime/save-intents.sqlite3').exists()
