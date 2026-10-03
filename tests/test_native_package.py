from datetime import datetime
from pathlib import Path

import pytest

from tistory_growth_os.delivery.native_package import load_native_package
from tistory_growth_os.artifacts.review_contract import ReviewCode
from tistory_growth_os.contracts.json_decode import JsonDecodeError
from tistory_growth_os.delivery.native_authority import PilotAuthority


def fixture_package(root: Path) -> Path:
    folder = root / 'content' / 'pilot'
    folder.mkdir(parents=True)
    _ = (folder / 'article.html').write_text('<p>본문</p>' + ''.join(f'{{{{MEDIA{i}}}}}' for i in range(1, 5)))
    _ = (folder / 'evidence.md').write_text('fixture sources and policy')
    _ = (folder / 'quality.md').write_text('fixture quality review')
    media: list[str] = []
    for i in range(4):
        _ = (folder / f'{i}.jpg').write_bytes(b'fixture image' + bytes((i,)))
        media.append(f'{{"asset_id":"asset{i}","file":"{i}.jpg","alt":"설명 {i}"}}')
    manifest = '''{"schema_version":"native-reviewed-v1","body_algorithm":"tistory-article-structure-v1",
    "title":"검수 제목","scheduled_at":"2030-01-01T19:00:00+09:00",
    "event_at":"2030-01-01T01:00:00+09:00","selected_at":"2030-01-01T14:00:00+09:00",
    "evidence_checked_at":"2030-01-01T14:00:00+09:00","category":"생활정보","home_topic":"생활정보",
    "tags":["해안"],"representative":"asset0","media":[''' + ','.join(media) + ']}'
    _ = (folder / 'manifest.json').write_text(manifest)
    return folder


def test_native_package_requires_separate_exact_byte_review(tmp_path: Path) -> None:
    folder = fixture_package(tmp_path)
    now = datetime.fromisoformat('2030-01-01T15:00:00+09:00')
    package = load_native_package(tmp_path, folder, now)
    assert package.article.valid()
    assert package.review(now).code is ReviewCode.REQUIRED
    before = package.article.intent.package_digest
    _ = (folder / 'quality.md').write_text('changed review evidence')
    assert load_native_package(tmp_path, folder, now).article.intent.package_digest != before


@pytest.mark.parametrize('change', ['expired', 'future_event', 'traversal', 'unknown_key'])
def test_native_package_rejects_unsafe_or_expired_inputs(tmp_path: Path, change: str) -> None:
    folder = fixture_package(tmp_path)
    path = folder / 'manifest.json'
    source = path.read_text()
    changes = {'expired': ('2030-01-01T01:00:00+09:00', '2029-12-31T19:00:00+09:00'),
               'future_event': ('2030-01-01T01:00:00+09:00', '2030-01-01T18:00:00+09:00'),
               'traversal': ('0.jpg', '../0.jpg'), 'unknown_key': ('"title":', '"unreviewed":true,"title":')}
    _ = path.write_text(source.replace(*changes[change]))
    with pytest.raises(JsonDecodeError if change in ('traversal', 'unknown_key') else ValueError):
        _ = load_native_package(tmp_path, folder, datetime.fromisoformat('2030-01-01T15:00:00+09:00'))


def test_pilot_authority_rechecks_review_and_every_payload_before_save(tmp_path: Path) -> None:
    folder = fixture_package(tmp_path)
    manifest = folder / 'manifest.json'
    _ = manifest.write_text(manifest.read_text().replace('2030-01-01', '2026-09-20'))
    now = datetime.fromisoformat('2026-09-20T15:00:00+09:00')
    package = load_native_package(tmp_path, folder, now)
    digest = package.article.intent.package_digest
    authority_file = tmp_path / 'authority.json'
    _ = authority_file.write_text('{"scope":"one-slot-native-reservation","approval_id":"owner-20260920-independent-pilot","scheduled_at":"2026-09-20T19:00:00+09:00","package_digest":"' + digest + '","valid_until":"2026-09-20T18:59:00+09:00"}')
    authority = PilotAuthority(authority_file, package)
    assert authority(package.article.intent, now) == ('REVIEW_REQUIRED',)
    reviews = tmp_path / 'contracts' / 'reviews'
    reviews.mkdir(parents=True)
    _ = (reviews / (digest + '.json')).write_text('{"schema_version":"1.0.0","scope":"local_package_only","review_id":"review_fixture","reviewer_id":"fixture_agent","reviewer_kind":"independent_agent","decision":"approved","subject_sha256":"' + digest + '","reviewed_at":"2026-09-20T14:30:00+09:00","valid_until":"2026-09-20T20:00:00+09:00","evidence_valid_until":"2026-09-21T01:00:00+09:00","policy_valid_until":"2026-09-21T00:00:00+09:00"}')
    assert authority(package.article.intent, now) == ()
    assert authority(package.article.intent, datetime.fromisoformat('2026-09-20T19:00:00+09:00')) == ('pilot_scope_or_deadline',)
    _ = (folder / 'quality.md').write_text('changed bytes')
    assert authority(package.article.intent, now) == ('package_changed',)
