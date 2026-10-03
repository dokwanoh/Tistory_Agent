from ..site_config import blog_host
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.sync_api import Page, TimeoutError as BrowserTimeout

from ..domain.ids import PostId
from .reservation_readback import KST


class ManagerVisibility(StrEnum):
    PUBLIC = 'public'
    PRIVATE = 'private'
    PROTECTED = 'protected'


@dataclass(frozen=True, slots=True)
class ManagerPostSummary:
    post_id: PostId
    display_title: str
    url: str
    category: str
    listed_at: datetime
    visibility: ManagerVisibility | None
    reserved: bool


def read_manager_inventory(page: Page) -> frozenset[PostId] | None:
    collected: set[PostId] = set()
    expected_total: int | None = None
    for number in range(1, 1001):
        url = urlsplit(page.url)
        query = parse_qs(url.query, keep_blank_values=True)
        if (url.scheme != 'https' or url.netloc != blog_host()
                or url.path.rstrip('/') != '/manage/posts' or url.fragment
                or query.get('category', ['-3']) != ['-3']
                or query.get('visibility', ['all']) != ['all']
                or query.get('searchKeyword', ['']) != ['']
                or query.get('page', ['1']) != [str(number)]):
            return None
        heading = page.get_by_role('heading', name='티스토리 관리센터 본문', exact=True)
        count = page.locator('#mArticle h3 .txt_count')
        if heading.count() != 1 or count.count() != 1:
            return None
        try:
            page.locator('#mArticle input[id^="inpCheck"]').first.wait_for(state='attached', timeout=5000)
        except BrowserTimeout:
            return None
        total_text = count.inner_text().strip().replace(',', '')
        if re.fullmatch(r'[0-9]+', total_text) is None:
            return None
        total = int(total_text)
        if expected_total is None:
            expected_total = total
        if total != expected_total:
            return None
        current: set[PostId] = set()
        for checkbox in page.locator('#mArticle input[id^="inpCheck"]').all():
            identifier = checkbox.get_attribute('id')
            match_id = re.fullmatch(r'inpCheck([1-9][0-9]*)', identifier or '')
            if match_id is None:
                return None
            post_id = PostId(match_id.group(1))
            if post_id in current or post_id in collected:
                return None
            current.add(post_id)
        collected.update(current)
        if len(collected) == expected_total:
            return frozenset(collected)
        if not current or len(collected) > expected_total:
            return None
        next_page = page.locator('.list_paging a.link_num').filter(has_text=re.compile(f'^{number + 1}$'))
        if next_page.count() != 1:
            return None
        destination = urljoin(page.url, next_page.get_attribute('href') or '')
        parsed = urlsplit(destination)
        if (parsed.scheme != 'https' or parsed.netloc != blog_host()
                or parsed.path.rstrip('/') != '/manage/posts'):
            return None
        next_page.click(timeout=5000)
        page.wait_for_url(destination, timeout=10000)
        try:
            page.locator(f'#inpCheck{min(current)}').wait_for(state='detached', timeout=5000)
        except BrowserTimeout:
            return None
    return None


def read_manager_post(page: Page, post_id: PostId) -> ManagerPostSummary | None:
    original_url = page.url
    parsed = urlsplit(original_url)
    if parsed.scheme != 'https' or parsed.netloc != blog_host() or parsed.path.rstrip('/') != '/manage/posts':
        return None
    if re.fullmatch(r'[1-9][0-9]*', post_id) is None:
        return None
    if page.get_by_role('heading', name='티스토리 관리센터 본문', exact=True).count() != 1:
        return None
    checkbox = page.locator(f'#inpCheck{post_id}')
    if checkbox.count() != 1:
        return None
    row = checkbox.locator('xpath=ancestor::li[1]')
    title = row.locator('a.link_cont')
    category = row.locator('.txt_cate')
    date = row.locator('.txt_info:not(.txt_ellip)')
    setting = row.locator('.btn_opt > .txt_ellip')
    if any(item.count() != 1 for item in (row, title, category, date, setting)):
        return None
    display_title = title.inner_text(timeout=3000).strip()
    target_url = title.get_attribute('href', timeout=3000)
    if not display_title or target_url is None:
        return None
    target = urlsplit(target_url)
    if (target.scheme != 'https' or target.netloc != blog_host()
            or target.query or target.fragment or target.path in ('', '/')
            or target.path.startswith('/manage')):
        return None
    stamp = date.inner_text(timeout=3000).strip()
    if re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}', stamp) is None:
        return None
    try:
        listed_at = datetime.strptime(stamp, '%Y-%m-%d %H:%M').replace(tzinfo=KST)
    except ValueError:
        return None
    marker = title.locator('.info_status')
    if marker.count() > 1:
        return None
    reserved = marker.count() == 1
    if reserved and (not marker.is_visible() or marker.inner_text(timeout=3000).strip() != '[예약]'):
        return None
    setting_text = setting.inner_text(timeout=3000).strip()
    visibility = {'공개': ManagerVisibility.PUBLIC, '비공개': ManagerVisibility.PRIVATE,
                  '보호': ManagerVisibility.PROTECTED}.get(setting_text)
    category_text = category.inner_text(timeout=3000).strip()
    if ((reserved and bool(setting_text)) or (not reserved and visibility is None)
            or page.url != original_url):
        return None
    return ManagerPostSummary(post_id, display_title, target_url, category_text, listed_at, visibility, reserved)
