from pathlib import Path

import pytest

from tests.preparation_fixture import NOW
from tests.test_preparation_publication import grant
from tests.test_preparation_v2 import EditorialFixture, v2_run
from tistory_growth_os.delivery.immediate_package import ImmediateAuthority, load_immediate_package
from tistory_growth_os.domain.publishing_errors import PublishingInvariantError
from tistory_growth_os.preparation.publication import PublicationGrant
from tistory_growth_os.preparation.runner import execute


def test_new_preparation_binds_unchanged_publisher(tmp_path: Path) -> None:
    run = v2_run(tmp_path)
    package_path = execute(run, EditorialFixture(('revise',)))
    approval = PublicationGrant.read(run, grant(tmp_path))
    authority = approval.bind(package_path)
    package = load_immediate_package(tmp_path, package_path, NOW)
    assert ImmediateAuthority(authority, package)(package.article.intent, NOW) == ()
    assert approval.bind(package_path) == authority


def test_new_preparation_real_publisher_respects_handoff_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str],
) -> None:
    run = v2_run(tmp_path)
    package = execute(run, EditorialFixture())
    approval = PublicationGrant.read(run, grant(tmp_path))
    original_bind = PublicationGrant.bind

    def stop_after_binding(self: PublicationGrant, folder: Path) -> Path:
        authority = original_bind(self, folder)
        stop = tmp_path / '.artifacts/native-runtime/STOP'
        stop.parent.mkdir(parents=True)
        _ = stop.write_text('fixture pause at handoff')
        return authority

    monkeypatch.setattr(PublicationGrant, 'bind', stop_after_binding)
    assert approval.publish(package) == 2
    assert 'kill_switch' in capfd.readouterr().out
    assert not (tmp_path / '.artifacts/native-runtime/save-intents.sqlite3').exists()


def test_new_preparation_cannot_bind_mutated_package(tmp_path: Path) -> None:
    run = v2_run(tmp_path)
    package = execute(run, EditorialFixture())
    _ = (package / 'article.html').write_text('changed after independent review')
    approval = PublicationGrant.read(run, grant(tmp_path))
    with pytest.raises(PublishingInvariantError, match='BODY_INVALID'):
        _ = approval.bind(package)
