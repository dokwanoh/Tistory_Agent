import json
from pathlib import Path

import pytest

from tistory_growth_os.onboarding import Profile, SetupError, save_profile
from tistory_growth_os.site_config import blog_host
from tistory_growth_os.site_config import configured_model, require_model_execution


def profile() -> Profile:
    return Profile('https://fresh-blog.tistory.com', ('IT/소프트웨어',), '초보 개발자',
                   '친절한 설명', 'available-model', 2, 0)


def test_setup_creates_private_dry_run_configuration(tmp_path: Path) -> None:
    # Given: a fresh project with no prior identity or permission.
    candidate = profile()
    # When: the interview is saved.
    path = save_profile(tmp_path, candidate)
    # Then: configuration is local and cannot grant publication.
    data = json.loads(path.read_text())
    assert data['blog_url'] == 'https://fresh-blog.tistory.com'
    assert data['publish_mode'] == 'dry_run'
    assert data['external_write_allowed'] is False
    assert data['schedule_enabled'] is False
    assert (tmp_path / '.artifacts/native-runtime/STOP').is_file()
    assert path.stat().st_mode & 0o777 == 0o600


def test_setup_preserves_existing_configuration(tmp_path: Path) -> None:
    # Given: existing owner configuration.
    path = save_profile(tmp_path, profile())
    before = path.read_bytes()
    # When: setup is accidentally repeated.
    with pytest.raises(SetupError):
        save_profile(tmp_path, profile())
    # Then: existing settings survive.
    assert path.read_bytes() == before


def test_invalid_stop_location_does_not_save_partial_setup(tmp_path: Path) -> None:
    from tistory_growth_os.artifacts.layout import ArtifactWriteError

    outside = tmp_path / 'outside'
    outside.mkdir()
    (tmp_path / '.artifacts').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactWriteError):
        save_profile(tmp_path, profile())
    assert not (tmp_path / '.local/profile.json').exists()


@pytest.mark.parametrize('url', [
    'http://fresh-blog.tistory.com', 'https://evil.test',
    'https://fresh-blog.tistory.com/entry/1', 'https://user:example@fresh-blog.tistory.com',
    'https://fresh-blog.tistory.com:443', 'https://fresh-blog.tistory.com?token=x',
])
def test_setup_rejects_unsafe_blog_targets(url: str) -> None:
    # Given / When / Then: only an exact HTTPS Tistory blog origin is accepted.
    with pytest.raises(SetupError):
        Profile(url, ('IT/소프트웨어',), '독자', '설명체', 'model', 1, 0)


def test_site_identity_uses_local_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a different new owner's local setup.
    save_profile(tmp_path, profile())
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('TISTORY_BLOG_HOST', raising=False)
    # When: a delivery boundary resolves its target.
    actual = blog_host()
    # Then: it uses this owner's identity, not a baked-in blog.
    assert actual == 'fresh-blog.tistory.com'


def test_unconfigured_site_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: no settings and no environment override.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('TISTORY_BLOG_HOST', raising=False)
    # When / Then: no destination is guessed.
    with pytest.raises(SetupError):
        blog_host()


def test_role_model_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('TISTORY_MODEL', 'default-model')
    monkeypatch.setenv('TISTORY_MODEL_WRITING', 'writer-model')
    assert configured_model('writing') == 'writer-model'
    assert configured_model('review') == 'default-model'


def test_paid_calls_require_separate_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('TISTORY_ALLOW_MODEL_EXECUTION', raising=False)
    with pytest.raises(SetupError):
        require_model_execution()


def test_delivery_rejects_a_different_blog(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone
    from tistory_growth_os.delivery.reservation_readback import ReservationTarget
    from tistory_growth_os.domain.ids import PostId
    from tistory_growth_os.domain.publishing_errors import PublishingInvariantError
    from tests.test_reservation_readback import target

    original_content = target().content
    monkeypatch.setenv('TISTORY_BLOG_HOST', 'fresh-blog.tistory.com')
    with pytest.raises(PublishingInvariantError):
        ReservationTarget(PostId('1'), 'https://example.tistory.com/1', datetime.now(timezone.utc), original_content)
