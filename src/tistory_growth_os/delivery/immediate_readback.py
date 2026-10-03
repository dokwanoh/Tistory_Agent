from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from ..domain.publishing_future import VerificationStatus
from .new_reservation_identity import SavedIdentity
from .reservation_readback import READBACK_TTL, ReservationCheck, ReservationContent, SavedVisibility, saved_tags_match


@dataclass(frozen=True, slots=True)
class ImmediateTarget:
    identity: SavedIdentity
    content: ReservationContent = field(repr=False)
    save_started_at: datetime


@dataclass(frozen=True, slots=True)
class ImmediateObservation:
    identity: SavedIdentity
    content: ReservationContent = field(repr=False)
    visibility: SavedVisibility
    published_at: datetime
    observed_at: datetime
    anonymous_public: bool


def verify_immediate_publication(
    target: ImmediateTarget, observed: ImmediateObservation | None, now: datetime,
) -> ReservationCheck:
    if observed is None:
        return ReservationCheck(VerificationStatus.UNKNOWN, ('missing_readback',))
    times = (now, target.save_started_at, observed.observed_at, observed.published_at)
    if any(stamp.utcoffset() is None for stamp in times):
        return ReservationCheck(VerificationStatus.UNKNOWN, ('timezone_required',))
    if not timedelta(0) <= now - observed.observed_at < READBACK_TTL:
        return ReservationCheck(VerificationStatus.UNKNOWN, ('readback_time',))
    comparisons = (
        ('identity', observed.identity == target.identity),
        ('content', replace(observed.content, tags=target.content.tags) == target.content
         and saved_tags_match(target.content.tags, observed.content.tags)),
        ('visibility', observed.visibility is SavedVisibility.PUBLIC),
        ('anonymous_public', observed.anonymous_public),
        ('publication_time', target.save_started_at.replace(second=0, microsecond=0)
         <= observed.published_at <= observed.observed_at),
        ('save_time', target.save_started_at <= observed.observed_at),
    )
    mismatches = tuple(name for name, matched in comparisons if not matched)
    status = VerificationStatus.MISMATCH if mismatches else VerificationStatus.VERIFIED
    return ReservationCheck(status, mismatches)
