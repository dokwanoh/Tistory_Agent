from ..site_config import blog_host
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
import re
from typing import Final
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ..domain.ids import MediaId, PostId
from ..domain.publishing_errors import PublishingInvariantError
from ..domain.publishing_future import VerificationStatus


KST: Final = ZoneInfo("Asia/Seoul")
READBACK_TTL: Final = timedelta(minutes=5)


def _aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise PublishingInvariantError("TIMEZONE_REQUIRED", "/time", "timezone-aware time required")


@dataclass(frozen=True, slots=True)
class ReservationMedia:
    asset_id: MediaId
    alt: str

    def __post_init__(self) -> None:
        if not self.asset_id.strip() or not self.alt.strip():
            raise PublishingInvariantError("MEDIA_INVALID", "/media", "asset identity and alt required")


@dataclass(frozen=True, slots=True)
class ReservationContent:
    title: str
    body_digest: str
    media: tuple[ReservationMedia, ...]
    representative: MediaId
    category: str | None
    home_topic: str
    tags: tuple[str, ...]

    def __post_init__(self) -> None:
        identities = tuple(item.asset_id for item in self.media)
        if len(identities) != 4 or len(set(identities)) != 4 or self.representative not in identities:
            raise PublishingInvariantError("MEDIA_INVALID", "/media", "four unique assets and matching representative required")
        if re.fullmatch(r"[0-9a-f]{64}", self.body_digest) is None:
            raise PublishingInvariantError("DIGEST_INVALID", "/body_digest", "SHA-256 required")
        if not self.title.strip() or not self.home_topic.strip():
            raise PublishingInvariantError("CONTENT_INVALID", "/content", "title and home topic required")
        if self.category is not None and not self.category.strip():
            raise PublishingInvariantError("CATEGORY_INVALID", "/category", "use None for no category")
        if len(set(self.tags)) != len(self.tags) or any(not tag.strip() for tag in self.tags):
            raise PublishingInvariantError("TAGS_INVALID", "/tags", "unique nonempty tags required")


@dataclass(frozen=True, slots=True)
class ReservationTarget:
    post_id: PostId
    url: str
    scheduled_at: datetime
    content: ReservationContent

    def __post_init__(self) -> None:
        _aware(self.scheduled_at)
        parsed = urlsplit(self.url)
        valid_url = (
            parsed.scheme == "https" and parsed.netloc == blog_host()
            and parsed.path not in ("", "/") and not parsed.query and not parsed.fragment
            and not parsed.path.startswith("/manage")
        )
        if not self.post_id.strip() or not valid_url:
            raise PublishingInvariantError("TARGET_INVALID", "/target", "post identity and exact blog URL required")


class SavedVisibility(StrEnum):
    SCHEDULED = "scheduled"
    PRIVATE = "private"
    PUBLIC = "public"


@dataclass(frozen=True, slots=True)
class ReservationObservation:
    target: ReservationTarget
    visibility: SavedVisibility
    observed_at: datetime

    def __post_init__(self) -> None:
        _aware(self.observed_at)


@dataclass(frozen=True, slots=True)
class ReservationCheck:
    status: VerificationStatus
    mismatches: tuple[str, ...]


def saved_tags_match(wanted: tuple[str, ...], saved: tuple[str, ...]) -> bool:
    mapping = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
    expected = tuple(sorted(tag.translate(mapping) for tag in wanted))
    actual = tuple(sorted(tag.translate(mapping) for tag in saved))
    return (len(set(expected)) == len(expected) and len(set(actual)) == len(actual)
            and expected == actual)


def verify_reservation(
    expected: ReservationTarget,
    observation: ReservationObservation | None,
    now: datetime,
) -> ReservationCheck:
    _aware(now)
    if observation is None:
        return ReservationCheck(VerificationStatus.UNKNOWN, ("missing_readback",))
    if now >= expected.scheduled_at:
        return ReservationCheck(VerificationStatus.UNKNOWN, ("release_check_required",))
    if not timedelta(0) <= now - observation.observed_at < READBACK_TTL:
        return ReservationCheck(VerificationStatus.UNKNOWN, ("readback_time",))
    actual = observation.target
    wanted = expected.content
    saved = actual.content
    comparisons = (
        ("post_id", expected.post_id == actual.post_id),
        ("url", expected.url == actual.url),
        ("scheduled_at", expected.scheduled_at == actual.scheduled_at),
        ("visibility", observation.visibility is SavedVisibility.SCHEDULED),
        ("title", wanted.title == saved.title),
        ("body_digest", wanted.body_digest == saved.body_digest),
        ("media", wanted.media == saved.media),
        ("representative", wanted.representative == saved.representative),
        ("category", wanted.category == saved.category),
        ("home_topic", wanted.home_topic == saved.home_topic),
        ("tags", saved_tags_match(wanted.tags, saved.tags)),
    )
    mismatches = tuple(name for name, matched in comparisons if not matched)
    status = VerificationStatus.MISMATCH if mismatches else VerificationStatus.VERIFIED
    return ReservationCheck(status, mismatches)


@dataclass(frozen=True, slots=True)
class DailySlot:
    release_at: datetime

    def __post_init__(self) -> None:
        _aware(self.release_at)
        local = self.release_at.astimezone(KST)
        if local.hour not in (8, 12, 19) or any((local.minute, local.second, local.microsecond)):
            raise PublishingInvariantError("SLOT_INVALID", "/release_at", "daily releases are 08:00, 12:00, 19:00 KST")

    @property
    def prepare_at(self) -> datetime:
        return self.release_at - timedelta(hours=3)

    @property
    def key(self) -> str:
        return f"{blog_host()}/{self.release_at.astimezone(KST):%Y-%m-%d/%H%M}"


def daily_slots(day: date) -> tuple[DailySlot, ...]:
    return tuple(DailySlot(datetime.combine(day, time(hour=hour), KST)) for hour in (8, 12, 19))
