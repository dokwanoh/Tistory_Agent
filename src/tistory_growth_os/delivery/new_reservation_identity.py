from ..site_config import blog_host
from dataclasses import dataclass
from datetime import datetime
import re

from ..domain.ids import PostId
from ..domain.publishing_errors import PublishingInvariantError
from .reservation_readback import DailySlot, ReservationContent, ReservationTarget


@dataclass(frozen=True, slots=True)
class NewReservationIntent:
    scheduled_at: datetime
    content: ReservationContent
    package_digest: str

    def __post_init__(self) -> None:
        _ = DailySlot(self.scheduled_at)
        if re.fullmatch(r"[0-9a-f]{64}", self.package_digest) is None:
            raise PublishingInvariantError("DIGEST_INVALID", "/package_digest", "SHA-256 required")


@dataclass(frozen=True, slots=True)
class SavedIdentity:
    post_id: PostId
    url: str

    def __post_init__(self) -> None:
        if (re.fullmatch(r"[1-9][0-9]*", self.post_id) is None
                or self.url != f"https://{blog_host()}/{self.post_id}"):
            raise PublishingInvariantError(
                "IDENTITY_INVALID", "/saved_identity", "numeric identity and matching canonical URL required",
            )


def bind_new_reservation(
    intent: NewReservationIntent,
    saved: SavedIdentity,
    prior_post_ids: frozenset[PostId] | None,
) -> ReservationTarget:
    """Bind a save receipt, not a verified result; None means inventory is incomplete."""
    if prior_post_ids is None:
        raise PublishingInvariantError("INVENTORY_REQUIRED", "/prior_post_ids", "complete pre-write inventory required")
    if saved.post_id in prior_post_ids:
        raise PublishingInvariantError("IDENTITY_PREEXISTING", "/post_id", "new save returned an existing identity")
    return ReservationTarget(saved.post_id, saved.url, intent.scheduled_at, intent.content)
