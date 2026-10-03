from ..site_config import blog_host
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..artifacts.layout import safe_output_root
from ..contracts.json_ast import JsonObject, JsonString, JsonValue
from ..contracts.json_decode import JsonDecodeError, parse_json_file


class ChromeProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PublisherProfile:
    logical_name: str
    blog_host: str
    profile_directory: str


_PROFILE_PATH: Final[str] = 'browser-profile'
_MARKER_PATH: Final[str] = 'tistory-profile.json'
_LOCAL_STATE_PATH: Final[str] = 'Local State'


def ensure_publisher_profile(root: Path) -> Path:
    expected_profile = PublisherProfile('Tistory Publisher', blog_host(), 'Default')
    profile_path = safe_output_root(root, _PROFILE_PATH).resolve()
    marker_path = profile_path / _MARKER_PATH
    local_state_path = profile_path / _LOCAL_STATE_PATH
    if not marker_path.is_file() or not local_state_path.is_file():
        raise ChromeProfileError('publisher_profile_identity_missing')
    try:
        marker_value = parse_json_file(marker_path)
        local_state_value = parse_json_file(local_state_path)
    except (OSError, UnicodeDecodeError, JsonDecodeError) as error:
        raise ChromeProfileError('publisher_profile_identity_unreadable') from error
    expected = {
        'logical_name': expected_profile.logical_name,
        'blog_host': expected_profile.blog_host,
        'profile_directory': expected_profile.profile_directory,
    }
    if _object_strings(marker_value) != expected:
        raise ChromeProfileError('publisher_profile_identity_mismatch')
    profile_value = _member(local_state_value, 'profile')
    info_cache = _member(profile_value, 'info_cache')
    if _member(info_cache, expected_profile.profile_directory) is None:
        raise ChromeProfileError('publisher_profile_directory_missing')
    return profile_path


def _member(value: JsonValue | None, key: str) -> JsonValue | None:
    if isinstance(value, JsonObject):
        return value.get(key)
    return None


def _object_strings(value: JsonValue) -> dict[str, str]:
    if not isinstance(value, JsonObject):
        return {}
    return {member.key: member.value.value for member in value.members if isinstance(member.value, JsonString)}
