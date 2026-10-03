import json
from pathlib import Path

import pytest

from tistory_growth_os.delivery.chrome_profile import ChromeProfileError, ensure_publisher_profile


def _profile(root: Path) -> Path:
    profile = root / 'browser-profile'
    profile.mkdir()
    (profile / 'Local State').write_text(json.dumps({'profile': {'info_cache': {'Default': {'name': '내 Chrome'}}}}))
    (profile / 'tistory-profile.json').write_text(json.dumps({
        'logical_name': 'Tistory Publisher',
        'blog_host': 'example.tistory.com',
        'profile_directory': 'Default',
    }))
    return profile


def test_ensure_publisher_profile_accepts_owned_profile(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    assert ensure_publisher_profile(tmp_path) == profile.resolve()


def test_ensure_publisher_profile_rejects_unidentified_profile(tmp_path: Path) -> None:
    profile = tmp_path / 'browser-profile'
    profile.mkdir()

    with pytest.raises(ChromeProfileError, match='identity_missing'):
        ensure_publisher_profile(tmp_path)
