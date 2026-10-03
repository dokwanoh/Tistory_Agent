from ..site_config import blog_host
from dataclasses import dataclass, field
import re
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.sync_api import Page

from .playwright_editor_readback import (
    EditorContentSnapshot, EditorTagsSnapshot, read_editor_content,
)
from .playwright_manager import ManagerPostSummary, ManagerVisibility
from .playwright_publish_settings import PublishSettingsSnapshot, read_publish_settings


@dataclass(frozen=True, slots=True)
class SavedReservationSnapshot:
    manager: ManagerPostSummary
    content: EditorContentSnapshot = field(repr=False)
    tags: EditorTagsSnapshot
    settings: PublishSettingsSnapshot
    representative_index: int


def read_saved_reservation(
    page: Page, manager: ManagerPostSummary, tags: EditorTagsSnapshot | None,
) -> SavedReservationSnapshot | None:
    if (not manager.reserved or manager.visibility is not None
            or tags is None or tags.post_id != manager.post_id):
        return None
    identity = manager.post_id
    content = read_editor_content(page, identity)
    settings = read_publish_settings(page, identity)
    if content is None or settings is None:
        return None
    target = urlsplit(manager.url)
    if (settings.scheduled_at != manager.listed_at or settings.existing_at is not None
            or settings.visibility is not ManagerVisibility.PUBLIC
            or settings.title != content.title
            or manager.display_title.removeprefix('[예약]').lstrip() != content.title
            or target.scheme != 'https' or target.netloc != blog_host()
            or target.query or target.fragment
            or unquote(target.path) not in (f'/{identity}', f'/entry/{settings.slug}')):
        return None
    panel = page.get_by_role('dialog').filter(has=page.locator('legend').filter(has_text='발행정보 입력폼'))
    thumbnail = panel.locator('.thumb_g')
    if thumbnail.count() != 1 or not thumbnail.is_visible():
        return None
    style = thumbnail.get_attribute('style', timeout=3000)
    match = re.fullmatch(r'background-image: url\("([^"\r\n]+)"\);', style or '')
    if match is None:
        return None
    location = urlsplit(match.group(1))
    if (location.scheme != 'https' or location.netloc != 'img1.daumcdn.net'
            or location.path != '/thumb/C170x170/' or location.fragment):
        return None
    originals = parse_qs(location.query).get('fname', [])
    if len(originals) != 1:
        return None
    indices = tuple(index for index, item in enumerate(content.media) if item.source_url == originals[0])
    if len(indices) != 1:
        return None
    if (read_editor_content(page, identity) != content
            or read_publish_settings(page, identity) != settings
            or thumbnail.get_attribute('style', timeout=3000) != style):
        return None
    return SavedReservationSnapshot(manager, content, tags, settings, indices[0])
