from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from tistory_growth_os.delivery import immediate_readback as reservation_readback
from tistory_growth_os.delivery.new_reservation_identity import SavedIdentity
from tistory_growth_os.delivery.reservation_readback import ReservationContent, ReservationMedia, SavedVisibility
from tistory_growth_os.domain.ids import MediaId, PostId
from tistory_growth_os.domain.publishing_future import VerificationStatus


@pytest.mark.parametrize('case', ['valid', 'missing', 'scheduled', 'private', 'anonymous',
                                 'title', 'media', 'identity', 'stale', 'future_readback',
                                 'old_publication', 'future_publication', 'naive_time'])
def test_immediate_readback_when_public_evidence_is_exact(case: str) -> None:
    # Given: exact content and a save interval, independent of any daily slot.
    media = tuple(ReservationMedia(MediaId(str(index)), f'사진 {index}') for index in range(4))
    content = ReservationContent('검수 제목', 'a' * 64, media, MediaId('0'), '생활정보', '국내여행', ('해안',))
    now = datetime.fromisoformat('2030-01-01T14:27:42+09:00')
    target = reservation_readback.ImmediateTarget(
        SavedIdentity(PostId('94'), 'https://example.tistory.com/94'), content, now - timedelta(seconds=15))
    observation = reservation_readback.ImmediateObservation(
        target.identity, content, SavedVisibility.PUBLIC,
        now.replace(second=0), now, True)
    variants = {
        'missing': None,
        'scheduled': replace(observation, visibility=SavedVisibility.SCHEDULED),
        'private': replace(observation, visibility=SavedVisibility.PRIVATE),
        'anonymous': replace(observation, anonymous_public=False),
        'title': replace(observation, content=replace(content, title='다른 제목')),
        'media': replace(observation, content=replace(content, media=tuple(reversed(content.media)))),
        'identity': replace(observation, identity=SavedIdentity(PostId('93'), 'https://example.tistory.com/93')),
        'stale': replace(observation, observed_at=now - timedelta(minutes=5)),
        'future_readback': replace(observation, observed_at=now + timedelta(seconds=1)),
        'old_publication': replace(observation, published_at=now - timedelta(days=1)),
        'future_publication': replace(observation, published_at=now + timedelta(minutes=1)),
        'naive_time': replace(observation, observed_at=now.replace(tzinfo=None)),
    }
    # When: evaluating immediate-public evidence rather than reservation evidence.
    result = reservation_readback.verify_immediate_publication(target, variants.get(case, observation), now)
    # Then: a scheduled state or missing anonymous evidence is never public success.
    assert (result.status is VerificationStatus.VERIFIED) == (case == 'valid')
    assert bool(result.mismatches) == (case != 'valid')


@pytest.mark.parametrize(('saved_tags', 'valid'), [
    (('ai', 'lg이노텍', '부품'), True),
    (('ai', 'lg이노텍', '다른태그'), False),
    (('ai', 'lg이노텍'), False),
    (('ai', 'lg이노텍', '부품', '추가'), False),
    (('ai', 'lg 이노텍', '부품'), False),
])
def test_immediate_readback_when_platform_lowercases_ascii_tags(
    saved_tags: tuple[str, ...], valid: bool,
) -> None:
    # Given: a reviewed uppercase tag identity and platform-normalized saved tags.
    media = tuple(ReservationMedia(MediaId(str(index)), f'사진 {index}') for index in range(4))
    content = ReservationContent('AI 제목', 'a' * 64, media, MediaId('0'), 'IT', 'IT 인터넷',
                                 ('AI', 'LG이노텍', '부품'))
    now = datetime.fromisoformat('2030-01-01T14:27:42+09:00')
    target = reservation_readback.ImmediateTarget(
        SavedIdentity(PostId('96'), 'https://example.tistory.com/96'), content, now - timedelta(seconds=15))
    observation = reservation_readback.ImmediateObservation(
        target.identity, replace(content, tags=saved_tags), SavedVisibility.PUBLIC,
        now.replace(second=0), now, True)
    # When: readback compares saved tag identities.
    result = reservation_readback.verify_immediate_publication(target, observation, now)
    # Then: only observed ASCII case normalization is equivalent, not tag changes.
    assert (result.status is VerificationStatus.VERIFIED) is valid


@pytest.mark.parametrize(('wanted', 'saved'), [
    (('Ä',), ('ä',)),
    (('ß',), ('ss',)),
    (('AI', 'ai'), ('AI', 'ai')),
    (('AI', 'ai'), ('ai',)),
])
def test_saved_tag_equivalence_rejects_unobserved_case_changes_and_collisions(
    wanted: tuple[str, ...], saved: tuple[str, ...],
) -> None:
    from tistory_growth_os.delivery.reservation_readback import saved_tags_match

    assert not saved_tags_match(wanted, saved)
