import os
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from .contracts.json_ast import JsonObject, JsonString
from .contracts.json_decode import parse_json_file
from .onboarding import SetupError, validate_host


PROFILE_PATH: Final = Path('.local/profile.json')


def profile_text(key: str) -> str:
    if not PROFILE_PATH.is_file():
        raise SetupError('onboarding_required')
    profile = parse_json_file(PROFILE_PATH)
    if not isinstance(profile, JsonObject):
        raise SetupError('invalid_profile')
    value = profile.get(key)
    if not isinstance(value, JsonString):
        raise SetupError('missing_profile_field')
    return value.value


def blog_host() -> str:
    configured = os.environ.get('TISTORY_BLOG_HOST')
    if configured:
        return validate_host(configured)
    url = urlsplit(profile_text('blog_url'))
    if (url.scheme != 'https' or url.netloc != url.hostname
            or url.path not in ('', '/') or url.query or url.fragment):
        raise SetupError('https_blog_origin_required')
    return validate_host(url.netloc)


def configured_model(stage: str = '') -> str:
    model = (os.environ.get('TISTORY_MODEL_' + stage.upper())
             or os.environ.get('TISTORY_MODEL') or profile_text('model'))
    if not model.strip():
        raise SetupError('model_selection_required')
    return model


def require_model_execution() -> None:
    if os.environ.get('TISTORY_ALLOW_MODEL_EXECUTION') != '1':
        raise SetupError('explicit_model_execution_approval_required')
