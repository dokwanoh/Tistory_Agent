from ..site_config import blog_host
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal
from urllib.parse import urlsplit

from playwright.sync_api import Page

from ..domain.ids import PostId
from .playwright_manager import ManagerVisibility
from .reservation_readback import KST, ReservationContent
from .new_reservation_identity import NewReservationIntent


def configure_publish_panel(page: Page, content: ReservationContent) -> bool:
    location = urlsplit(page.url)
    title = page.locator('#post-title-inp')
    if (location.scheme != 'https' or location.netloc != blog_host()
            or location.path.rstrip('/') != '/manage/newpost'
            or title.count() != 1 or title.input_value() != content.title):
        return False
    tags = page.get_by_role('link', name=re.compile(r'(?:^| )태그 수정$'))
    existing_tags = tuple(value.removeprefix('#').strip() for value in tags.all_inner_texts())
    if any(value not in content.tags for value in existing_tags) or len(set(existing_tags)) != len(existing_tags):
        return False
    category = content.category or '카테고리 없음'
    page.locator('#category-btn').click()
    choice = page.locator('#category-list').get_by_text(category, exact=True)
    if choice.count() != 1 or not choice.is_visible():
        return False
    choice.click()
    for tag in content.tags:
        if tag not in existing_tags:
            page.locator('#tagText').fill(tag)
            page.locator('#tagText').press('Enter')
    observed_tags = tuple(text.removeprefix('#').strip() for text in tags.all_inner_texts())
    if set(observed_tags) != set(content.tags) or len(observed_tags) != len(content.tags):
        return False
    page.locator('#publish-layer-btn').click()
    panel = page.get_by_role('dialog').filter(has=page.locator('legend').filter(has_text='발행정보 입력폼'))
    if panel.count() != 1 or panel.locator('.tit_publish').inner_text().strip() != content.title:
        return False
    panel.locator('#open20').check()
    panel.locator('#home_subject button').click()
    home = page.get_by_role('menuitem', name='- ' + content.home_topic, exact=True)
    if home.count() != 1 or not home.is_visible():
        return False
    home.click()
    return page.url == location.geturl()


def configure_new_reservation(page: Page, request: NewReservationIntent, *, dry_run: bool = True) -> Literal['dry_run', 'blocked', 'input_verified']:
    if dry_run:
        return 'dry_run'
    if not configure_publish_panel(page, request.content):
        return 'blocked'
    location = urlsplit(page.url)
    title = page.locator('#post-title-inp')
    category = request.content.category or '카테고리 없음'
    panel = page.get_by_role('dialog').filter(has=page.locator('legend').filter(has_text='발행정보 입력폼'))
    panel.get_by_role('button', name='현재', exact=True).click()
    panel.get_by_role('button', name='예약', exact=True).click()
    day = request.scheduled_at.astimezone(KST)
    if panel.locator('button.btn_reserve').inner_text().strip() != day.strftime('%Y-%m-%d'):
        return 'blocked'
    hour = panel.locator('#dateHour')
    minute = panel.locator('#dateMinute')
    hour.fill(day.strftime('%H'))
    minute.fill(day.strftime('%M'))
    minute.press('Tab')
    selected_category = page.locator('#category-btn').inner_text().replace('더보기', '').strip()
    if (hour.input_value() != day.strftime('%H') or minute.input_value() != day.strftime('%M')
            or not panel.locator('#open20').is_checked()
            or panel.locator('.btn_date.on').inner_text().strip() != '예약'
            or panel.locator('#home_subject button .mce-txt').inner_text().strip() != request.content.home_topic
            or selected_category != category or title.input_value() != request.content.title
            or page.url != location.geturl()):
        return 'blocked'
    return 'input_verified'


def configure_immediate_publication(
    page: Page, content: ReservationContent, *, dry_run: bool = True,
) -> Literal['dry_run', 'blocked', 'input_verified']:
    if dry_run:
        return 'dry_run'
    location = urlsplit(page.url)
    if (location.scheme != 'https' or location.netloc != blog_host()
            or location.path.rstrip('/') != '/manage/newpost'):
        return 'blocked'
    panel = page.get_by_role('dialog').filter(has=page.locator('legend').filter(has_text='발행정보 입력폼'))
    title = page.locator('#post-title-inp')
    category = page.locator('#category-btn')
    if (panel.count() != 1 or not panel.is_visible() or title.count() != 1
            or category.count() != 1 or title.input_value() != content.title):
        return 'blocked'
    panel_title = panel.locator('.tit_publish')
    home = panel.locator('#home_subject button .mce-txt')
    public = panel.locator('#open20')
    current = panel.get_by_role('button', name='현재', exact=True)
    tags = page.get_by_role('link', name=re.compile(r'(?:^| )태그 수정$'), include_hidden=True)
    observed_tags = tuple(sorted(text.removeprefix('#').strip() for text in tags.all_inner_texts()))
    if (any(item.count() != 1 or not item.is_visible() for item in (panel_title, home, public, current))
            or panel_title.inner_text().strip() != content.title
            or home.inner_text().strip() != content.home_topic
            or category.inner_text().replace('더보기', '').strip() != (content.category or '카테고리 없음')
            or observed_tags != tuple(sorted(content.tags))):
        return 'blocked'
    public.check()
    current.click()
    selected = panel.locator('.btn_date.on')
    if (selected.count() != 1 or selected.inner_text().strip() != '현재'
            or not public.is_checked() or page.url != location.geturl()):
        return 'blocked'
    return 'input_verified'


@dataclass(frozen=True, slots=True)
class PublishSettingsSnapshot:
    post_id: PostId
    title: str
    visibility: ManagerVisibility
    home_topic: str
    existing_at: datetime | None
    slug: str
    scheduled_at: datetime | None


def read_publish_settings(page: Page, post_id: PostId) -> PublishSettingsSnapshot | None:
    original_url = page.url
    parsed = urlsplit(original_url)
    if (re.fullmatch(r'[1-9][0-9]*', post_id) is None
            or parsed.scheme != 'https' or parsed.netloc != blog_host()
            or parsed.path != f'/manage/newpost/{post_id}'):
        return None
    panel = page.get_by_role('dialog').filter(has=page.locator('legend').filter(has_text='발행정보 입력폼'))
    if panel.count() != 1 or not panel.is_visible():
        return None
    title = panel.locator('.tit_publish')
    home = panel.locator('#home_subject button .mce-txt')
    date = panel.locator('.btn_date.on')
    selected = panel.locator('input[name=basicSet]:checked')
    slug_input = panel.locator('#urlPublish')
    if any(item.count() != 1 for item in (title, home, date, selected, slug_input)):
        return None
    stamp = date.inner_text(timeout=3000).strip()
    reserved = stamp == '예약'
    if reserved:
        day = panel.locator('button.btn_reserve')
        hour = panel.locator('input#dateHour[type=number]')
        minute = panel.locator('input#dateMinute[type=number]')
        if any(item.count() != 1 or not item.is_visible() for item in (day, hour, minute)):
            return None
        day_text = day.inner_text(timeout=3000).strip()
        hour_text = hour.input_value(timeout=3000)
        minute_text = minute.input_value(timeout=3000)
        if any(re.fullmatch(r'[0-9]{1,2}', value) is None for value in (hour_text, minute_text)):
            return None
        stamp = f'{day_text} {hour_text.zfill(2)}:{minute_text.zfill(2)}'
    if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}', stamp) is None:
        return None
    try:
        observed_at = datetime.strptime(stamp, '%Y-%m-%d %H:%M').replace(tzinfo=KST)
    except ValueError:
        return None
    visibility = {'20': ManagerVisibility.PUBLIC, '15': ManagerVisibility.PROTECTED,
                  '0': ManagerVisibility.PRIVATE}.get(selected.input_value(timeout=3000))
    title_text = title.inner_text(timeout=3000).strip()
    home_text = home.inner_text(timeout=3000).strip()
    slug = slug_input.input_value(timeout=3000)
    if (visibility is None or not title_text or not home_text or not slug.strip()
            or any(character in slug for character in '/?#%\\') or slug in ('.', '..')
            or page.url != original_url):
        return None
    return PublishSettingsSnapshot(post_id, title_text, visibility, home_text,
                                   None if reserved else observed_at, slug,
                                   observed_at if reserved else None)
