from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tistory_growth_os.delivery import reservation_readback as readback
from tistory_growth_os.delivery.save_intents import SaveIntentJournal
from tistory_growth_os.domain.ids import MediaId, PostId
from tistory_growth_os.domain.publishing_future import VerificationStatus
from tistory_growth_os.domain.publishing_errors import PublishingInvariantError


def target() -> readback.ReservationTarget:
    media = tuple(readback.ReservationMedia(MediaId(str(n)), f"그림 {n}") for n in range(4))
    content = readback.ReservationContent("예약 테스트", "a" * 64, media, MediaId("0"), "생활정보", "생활정보", ("정보",))
    return readback.ReservationTarget(PostId("79"), "https://example.tistory.com/79", datetime.fromisoformat("2026-09-13T12:00:00+09:00"), content)


def observed() -> readback.ReservationObservation:
    return readback.ReservationObservation(target(), readback.SavedVisibility.SCHEDULED, datetime.fromisoformat("2026-09-13T11:55:00+09:00"))


def test_exact_future_reservation_verifies_without_publication_claim() -> None:
    result = readback.verify_reservation(target(), observed(), observed().observed_at)
    assert result.status is VerificationStatus.VERIFIED
    assert result.mismatches == ()


def test_missing_readback_is_unknown() -> None:
    result = readback.verify_reservation(target(), None, observed().observed_at)
    assert result.status is VerificationStatus.UNKNOWN


def test_reservation_readback_accepts_saved_ascii_tag_normalization() -> None:
    expected = replace(target(), content=replace(target().content, tags=('AI', 'LG이노텍')))
    saved = replace(expected, content=replace(expected.content, tags=('ai', 'lg이노텍')))
    observation = replace(observed(), target=saved)
    result = readback.verify_reservation(expected, observation, observation.observed_at)
    assert result.status is VerificationStatus.VERIFIED


@pytest.mark.parametrize("field", ["title", "body_digest", "media", "representative", "category", "home_topic", "tags"])
def test_changed_content_field_blocks_success(field: str) -> None:
    content = target().content
    changes = {
        "title": replace(content, title="다른 제목"),
        "body_digest": replace(content, body_digest="b" * 64),
        "media": replace(content, media=tuple(reversed(content.media))),
        "representative": replace(content, representative=MediaId("1")),
        "category": replace(content, category=None),
        "home_topic": replace(content, home_topic="교육"),
        "tags": replace(content, tags=("변경",)),
    }
    observation = replace(observed(), target=replace(target(), content=changes[field]))
    result = readback.verify_reservation(target(), observation, observation.observed_at)
    assert result.status is VerificationStatus.MISMATCH
    assert field in result.mismatches


def test_changed_alt_blocks_success() -> None:
    content = target().content
    media = (replace(content.media[0], alt="다른 설명"), *content.media[1:])
    observation = replace(observed(), target=replace(target(), content=replace(content, media=media)))
    assert readback.verify_reservation(target(), observation, observation.observed_at).status is VerificationStatus.MISMATCH


@pytest.mark.parametrize("visibility", [readback.SavedVisibility.PRIVATE, readback.SavedVisibility.PUBLIC])
def test_nonreservation_visibility_is_not_scheduled(visibility: readback.SavedVisibility) -> None:
    observation = replace(observed(), visibility=visibility)
    assert "visibility" in readback.verify_reservation(target(), observation, observation.observed_at).mismatches


@pytest.mark.parametrize("minutes", [-1, 5, 6])
def test_future_or_stale_readback_is_unknown(minutes: int) -> None:
    now = observed().observed_at
    observation = replace(observed(), observed_at=now - timedelta(minutes=minutes))
    assert readback.verify_reservation(target(), observation, now).status is VerificationStatus.UNKNOWN


def test_release_deadline_requires_separate_public_checker() -> None:
    assert readback.verify_reservation(target(), observed(), target().scheduled_at).status is VerificationStatus.UNKNOWN


def test_naive_clock_is_rejected() -> None:
    with pytest.raises(PublishingInvariantError):
        readback.verify_reservation(target(), observed(), datetime(2026, 9, 13))


def test_equivalent_utc_schedule_matches() -> None:
    observation = replace(observed(), target=replace(target(), scheduled_at=target().scheduled_at.astimezone(timezone.utc)))
    assert readback.verify_reservation(target(), observation, observation.observed_at).status is VerificationStatus.VERIFIED


@pytest.mark.parametrize("change", ["id", "url", "time"])
def test_wrong_remote_identity_or_schedule_blocks(change: str) -> None:
    options = {
        "id": replace(target(), post_id=PostId("80")),
        "url": replace(target(), url="https://example.tistory.com/80"),
        "time": replace(target(), scheduled_at=target().scheduled_at + timedelta(minutes=1)),
    }
    observation = replace(observed(), target=options[change])
    assert readback.verify_reservation(target(), observation, observation.observed_at).status is VerificationStatus.MISMATCH


def test_daily_slots_have_three_hour_preparation_and_canonical_keys() -> None:
    slots = readback.daily_slots(date(2026, 9, 13))
    assert [slot.release_at.hour for slot in slots] == [8, 12, 19]
    assert [slot.prepare_at.hour for slot in slots] == [5, 9, 16]
    assert slots[1].key == "example.tistory.com/2026-09-13/1200"


def test_uncertain_readback_does_not_unlock_sqlite_retry(tmp_path: Path) -> None:
    slot = readback.daily_slots(date(2026, 9, 13))[1]
    journal = SaveIntentJournal(tmp_path / "attempt.sqlite3")
    assert journal.claim(slot.key, "a" * 64)
    result = readback.verify_reservation(target(), None, observed().observed_at)
    assert result.status is VerificationStatus.UNKNOWN
    assert not SaveIntentJournal(tmp_path / "attempt.sqlite3").claim(slot.key, "a" * 64)


@pytest.mark.parametrize("stamp", ["2026-09-13T12:00:00", "2026-09-13T13:00:00+09:00", "2026-09-13T12:00:01+09:00"])
def test_invalid_daily_slot_cannot_create_unapproved_extra_slot(stamp: str) -> None:
    with pytest.raises(PublishingInvariantError):
        readback.DailySlot(datetime.fromisoformat(stamp))


@pytest.mark.parametrize("url", ["https://example.com/79", "http://example.tistory.com/79", "https://example.tistory.com/manage/posts", "https://example.tistory.com/79?token=example"])
def test_invalid_target_url_is_rejected(url: str) -> None:
    with pytest.raises(PublishingInvariantError):
        replace(target(), url=url)


def test_missing_image_cannot_construct_complete_observation() -> None:
    with pytest.raises(PublishingInvariantError):
        replace(target().content, media=target().content.media[:3])


def test_empty_alt_cannot_construct_complete_observation() -> None:
    with pytest.raises(PublishingInvariantError):
        readback.ReservationMedia(MediaId("0"), " ")
