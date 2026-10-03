from datetime import datetime
from pathlib import Path

import pytest

from tests.test_native_package import fixture_package
from tistory_growth_os.artifacts.review_contract import ReviewCode
from tistory_growth_os.contracts.json_decode import JsonDecodeError
from tistory_growth_os.delivery.immediate_package import ImmediateAuthority, load_immediate_package


@pytest.mark.parametrize('owner_supplied', [True, False])
def test_old_owner_topic_exempts_age_only(tmp_path: Path, owner_supplied: bool) -> None:
    # Given an old event with current evidence and an explicit owner-topic contract.
    folder = immediate_package_fixture(tmp_path)
    manifest = folder / 'manifest.json'
    raw = manifest.read_text().replace('native-immediate-v1',
        'native-immediate-owner-v1' if owner_supplied else 'native-immediate-v2')
    raw = raw.replace('2030-01-01T01:00:00', '2029-12-01T01:00:00')
    if owner_supplied:
        raw = raw.replace('"schema_version":', '"owner_topic_reference":"owner-request-20300101",'
            + '"owner_source_url":"https://www.youtube.com/watch?v=example", "schema_version":')
    _ = manifest.write_text(raw)
    now = datetime.fromisoformat('2030-01-01T15:00:00+09:00')
    # When loading, then only owner-supplied material may pass the age criterion.
    if not owner_supplied:
        with pytest.raises(ValueError):
            _ = load_immediate_package(tmp_path, folder, now)
        return
    loaded = load_immediate_package(tmp_path, folder, now)
    assert loaded.review(now).code is ReviewCode.REQUIRED
    # Expired assembly/evidence validity is never waived.
    with pytest.raises(ValueError):
        _ = load_immediate_package(tmp_path, folder, datetime.fromisoformat('2030-01-02T15:00:00+09:00'))


def test_owner_version_requires_origin_fields(tmp_path: Path) -> None:
    folder = immediate_package_fixture(tmp_path)
    manifest = folder / 'manifest.json'
    _ = manifest.write_text(manifest.read_text().replace('native-immediate-v1', 'native-immediate-owner-v1'))
    with pytest.raises(JsonDecodeError):
        _ = load_immediate_package(tmp_path, folder, datetime.fromisoformat('2030-01-01T15:00:00+09:00'))


def immediate_package_fixture(root: Path) -> Path:
    folder = fixture_package(root)
    path = folder / 'manifest.json'
    _ = path.write_text(path.read_text().replace('native-reviewed-v1', 'native-immediate-v1')
        .replace('"scheduled_at":', '"operation_id":"manual-one","valid_until":'))
    return folder


@pytest.mark.parametrize('change', ['none', 'scheduled', 'expired', 'future', 'long_validity', 'traversal'])
def test_immediate_package_requires_distinct_fresh_contract(tmp_path: Path, change: str) -> None:
    # Given: a reviewed-format four-image package, with no scheduled slot.
    folder = immediate_package_fixture(tmp_path)
    manifest = folder / 'manifest.json'
    changes = {'none': ('UNUSED', 'UNUSED'), 'scheduled': ('"valid_until":', '"scheduled_at":'),
               'expired': ('T19:00:00', 'T15:00:00'), 'future': ('T01:00:00', 'T16:00:00'),
               'long_validity': ('2030-01-01T19:00:00', '2030-01-02T02:00:00'),
               'traversal': ('0.jpg', '../0.jpg')}
    _ = manifest.write_text(manifest.read_text().replace(*changes[change]))
    now = datetime.fromisoformat('2030-01-01T15:00:00+09:00')
    # When / Then: invalid contracts fail closed; source bytes need separate review.
    if change != 'none':
        with pytest.raises((ValueError, JsonDecodeError)):
            _ = load_immediate_package(tmp_path, folder, now)
        return
    package = load_immediate_package(tmp_path, folder, now)
    assert package.article.valid()
    assert package.review(now).code is ReviewCode.REQUIRED
    assert package.article.intent.operation_id == 'manual-one'


def test_immediate_authority_binds_review_bytes_operation_and_clock(tmp_path: Path) -> None:
    # Given: one scope-bound authority and independently reviewed package.
    folder = immediate_package_fixture(tmp_path)
    now = datetime.fromisoformat('2030-01-01T15:00:00+09:00')
    package = load_immediate_package(tmp_path, folder, now)
    digest = package.article.intent.package_digest
    authority_file = tmp_path / 'authority.json'
    source = ('{"scope":"one-article-native-immediate","approval_id":"fixture-owner",'
        + '"operation_id":"manual-one","approved_at":"2030-01-01T14:30:00+09:00",'
        + '"package_digest":"' + digest + '","valid_until":"2030-01-01T18:00:00+09:00"}')
    _ = authority_file.write_text(source)
    authority = ImmediateAuthority(authority_file, package)
    assert authority(package.article.intent, now) == ('REVIEW_REQUIRED',)
    reviews = tmp_path / 'contracts' / 'reviews'
    reviews.mkdir(parents=True)
    _ = (reviews / (digest + '.json')).write_text('{"schema_version":"1.0.0","scope":"local_package_only",'
        + '"review_id":"review_fixture","reviewer_id":"fixture_agent","reviewer_kind":"independent_agent",'
        + '"decision":"approved","subject_sha256":"' + digest + '","reviewed_at":"2030-01-01T14:30:00+09:00",'
        + '"valid_until":"2030-01-01T20:00:00+09:00","evidence_valid_until":"2030-01-02T01:00:00+09:00",'
        + '"policy_valid_until":"2030-01-02T00:00:00+09:00"}')
    # When / Then: exact authority succeeds, but expiry, wrong identity and changed bytes do not.
    assert authority(package.article.intent, now) == ()
    assert authority(package.article.intent, datetime.fromisoformat('2030-01-01T18:00:00+09:00'))
    _ = authority_file.write_text(source.replace('manual-one', 'manual-two'))
    assert authority(package.article.intent, now)
    _ = authority_file.write_text(source)
    _ = (folder / 'quality.md').write_text('changed bytes')
    assert authority(package.article.intent, now) == ('package_changed',)
