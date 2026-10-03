from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from typing import Final
from urllib.parse import urlsplit

from .artifacts.layout import safe_output_root


TOPICS: Final = ('금융/보험', '법률', '부동산', 'IT/소프트웨어')


@dataclass(frozen=True, slots=True)
class SetupError(ValueError):
    code: str

def validate_host(host: str) -> str:
    if re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.tistory\.com', host) is None:
        raise SetupError('invalid_blog_host')
    if host in ('www.tistory.com', 'notice.tistory.com'):
        raise SetupError('blog_subdomain_required')
    return host


@dataclass(frozen=True, slots=True)
class Profile:
    blog_url: str
    topics: tuple[str, ...]
    audience: str
    tone: str
    model: str
    weekly_posts: int
    monthly_budget_krw: int

    def __post_init__(self) -> None:
        url = urlsplit(self.blog_url)
        if (url.scheme != 'https' or url.netloc != url.hostname
                or url.path not in ('', '/') or url.query or url.fragment):
            raise SetupError('https_blog_origin_required')
        _ = validate_host(url.netloc)
        if not self.topics or any(topic not in TOPICS for topic in self.topics):
            raise SetupError('unsupported_topic')
        if len(set(self.topics)) != len(self.topics):
            raise SetupError('duplicate_topic')
        if not self.audience.strip() or not self.tone.strip():
            raise SetupError('audience_and_tone_required')
        if any(len(value) > 200 or '\n' in value for value in (self.audience, self.tone)):
            raise SetupError('editorial_preference_too_long')
        if self.model and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._:-]{0,99}', self.model) is None:
            raise SetupError('invalid_model_id')
        if not 0 <= self.weekly_posts <= 21 or not 0 <= self.monthly_budget_krw <= 10_000_000:
            raise SetupError('budget_or_cadence_out_of_range')


def save_profile(root: Path, profile: Profile) -> Path:
    stop = safe_output_root(root, '.artifacts/native-runtime/STOP')
    local = root / '.local'
    if local.is_symlink():
        raise SetupError('local_directory_symlink_forbidden')
    path = local / 'profile.json'
    if path.exists() or path.is_symlink():
        raise SetupError('profile_already_exists')
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.touch(exist_ok=True)
    local.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {**asdict(profile), 'schema_version': 1, 'publish_mode': 'dry_run',
               'external_write_allowed': False, 'schedule_enabled': False}
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise SetupError('profile_already_exists') from error
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        _ = stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    return path


def main() -> int:
    try:
        url = input('블로그 주소 (https://블로그ID.tistory.com): ').strip().rstrip('/')
        print('주제: ' + ', '.join(TOPICS))
        topics = tuple(value.strip() for value in input('운영 주제 (쉼표 구분): ').split(','))
        audience = input('주요 독자 [일반 독자]: ').strip() or '일반 독자'
        tone = input('문체 [친절한 설명체]: ').strip() or '친절한 설명체'
        model = input('현재 계정에서 사용 가능한 모델 ID [나중에 설정]: ').strip()
        weekly = int(input('희망 주간 글 수 (예약은 활성화하지 않음) [0]: ').strip() or '0')
        budget = int(input('월 비용 상한 원 (0이면 유료 실행 금지) [0]: ').strip() or '0')
        _ = save_profile(Path.cwd(), Profile(url, topics, audience, tone, model, weekly, budget))
    except (SetupError, ValueError, OSError, EOFError) as error:
        print('설정 중단: ' + (error.code if isinstance(error, SetupError) else type(error).__name__))
        return 2
    print('로컬 설정을 저장했습니다. 드라이런 상태이며 실제 게시·예약은 비활성입니다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
