from ..site_config import blog_host
from dataclasses import dataclass, field, replace
from datetime import datetime

from ..domain.ids import MediaId
from .editor_body_fingerprint import article_body_digest
from .native_article_source import NativeAlt
from .playwright_saved_reservation import SavedReservationSnapshot
from .reservation_readback import (
    ReservationContent, ReservationMedia, ReservationObservation, ReservationTarget, SavedVisibility,
)


@dataclass(frozen=True, slots=True)
class UploadedAsset:
    asset_id: MediaId
    source_url: str = field(repr=False)
    filename: str


def structural_reservation_observation(
    snapshot: SavedReservationSnapshot, uploads: tuple[UploadedAsset, ...],
    media: tuple[NativeAlt, ...], observed_at: datetime,
) -> ReservationObservation | None:
    digest = article_body_digest(snapshot.content.body_html, media)
    observation = reservation_observation(snapshot, uploads, observed_at)
    if digest is None or observation is None:
        return None
    content = replace(observation.target.content, body_digest=digest)
    return replace(observation, target=replace(observation.target, content=content))


def reservation_observation(
    snapshot: SavedReservationSnapshot,
    uploads: tuple[UploadedAsset, ...],
    observed_at: datetime,
) -> ReservationObservation | None:
    if (len(uploads) != 4 or len({item.asset_id for item in uploads}) != 4
            or len({item.source_url for item in uploads}) != 4
            or any(not item.asset_id.strip() or not item.filename.strip() for item in uploads)
            or len(snapshot.content.media) != 4
            or snapshot.settings.scheduled_at is None
            or not 0 <= snapshot.representative_index < 4):
        return None
    mapped: list[ReservationMedia] = []
    for image in snapshot.content.media:
        matches = tuple(item for item in uploads
                        if item.source_url == image.source_url and item.filename == image.filename)
        if len(matches) != 1:
            return None
        mapped.append(ReservationMedia(matches[0].asset_id, image.alt))
    content = ReservationContent(
        snapshot.content.title, snapshot.content.body_sha256, tuple(mapped),
        mapped[snapshot.representative_index].asset_id, snapshot.manager.category,
        snapshot.settings.home_topic, tuple(sorted(snapshot.tags.tags)),
    )
    identity = snapshot.manager.post_id
    target = ReservationTarget(identity, f'https://{blog_host()}/{identity}',
                               snapshot.settings.scheduled_at, content)
    return ReservationObservation(target, SavedVisibility.SCHEDULED, observed_at)
