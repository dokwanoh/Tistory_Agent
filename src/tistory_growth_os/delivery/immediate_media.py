from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from ..domain.ids import MediaId
if TYPE_CHECKING:
    from .playwright_observation import UploadedAsset


@dataclass(frozen=True, slots=True)
class MediaBinding:
    asset_id: MediaId
    filename: str
    source_sha256: str


def media_bindings(uploads: tuple[UploadedAsset, ...]) -> tuple[MediaBinding, ...]:
    return tuple(MediaBinding(item.asset_id, item.filename, sha256(item.source_url.encode('utf-8')).hexdigest())
                 for item in uploads)
