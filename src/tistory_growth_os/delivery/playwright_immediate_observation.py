from ..site_config import blog_host
from contextlib import closing
from datetime import datetime
from hashlib import sha256
import re
from urllib.parse import parse_qs, unquote, urlsplit

from playwright.sync_api import BrowserContext, Page

from .editor_body_fingerprint import article_body_digest
from .immediate_readback import ImmediateObservation, ImmediateTarget
from .immediate_media import MediaBinding
from .new_reservation_identity import SavedIdentity
from .playwright_article_input import ImmediateArticleInput
from .playwright_editor_readback import read_editor_content, read_editor_tags
from .playwright_manager import ManagerVisibility, read_manager_post
from .playwright_publish_settings import read_publish_settings
from .reservation_readback import ReservationContent, ReservationMedia, SavedVisibility


def immediate_observation(
    page: Page, anonymous_context: BrowserContext, article: ImmediateArticleInput,
    target: ImmediateTarget, now: datetime, bindings: tuple[MediaBinding, ...],
) -> ImmediateObservation | None:
    if len(bindings) != 4:
        return None
    identity = target.identity.post_id
    _ = page.goto(f'https://{blog_host()}/manage/posts/', wait_until='domcontentloaded')
    page.locator(f'#inpCheck{identity}').wait_for(state='attached', timeout=10000)
    summary = read_manager_post(page, identity)
    if summary is None or summary.reserved or summary.visibility is not ManagerVisibility.PUBLIC:
        return None
    _ = page.goto(f'https://{blog_host()}/manage/newpost/{identity}', wait_until='domcontentloaded')
    page.locator('#post-title-inp').wait_for(state='visible', timeout=10000)
    body = page.frame_locator('#editor-tistory_ifr').locator('#tinymce')
    body.wait_for(timeout=10000)
    snapshot = read_editor_content(page, identity)
    tags = read_editor_tags(page, identity)
    category = page.locator('#category-btn').inner_text().replace('더보기', '').strip()
    if snapshot is None or tags is None or len(snapshot.media) != len(article.uploads):
        return None
    media: list[ReservationMedia] = []
    for image, upload, receipt in zip(snapshot.media, article.uploads, bindings, strict=True):
        if (image.filename != upload.path.name or receipt.asset_id != upload.asset_id
                or receipt.filename != image.filename
                or receipt.source_sha256 != sha256(image.source_url.encode('utf-8')).hexdigest()):
            return None
        media.append(ReservationMedia(upload.asset_id, image.alt))
    digest = article_body_digest(snapshot.body_html, article.media())
    if digest is None:
        return None
    native_text = ' '.join(body.inner_text().split())
    native_links = tuple(link.get_attribute('href') for link in body.locator('a').all())
    page.locator('#publish-layer-btn').click()
    panel = page.get_by_role('dialog').filter(has=page.locator('legend').filter(has_text='발행정보 입력폼'))
    try:
        settings = read_publish_settings(page, identity)
        thumbnail = panel.locator('.thumb_g')
        if settings is None or thumbnail.count() != 1:
            return None
        style = re.fullmatch(r'background-image: url\("([^"\r\n]+)"\);', thumbnail.get_attribute('style') or '')
        if style is None:
            return None
        cover = urlsplit(style.group(1))
        if cover.scheme != 'https' or cover.netloc != 'img1.daumcdn.net' or cover.path != '/thumb/C170x170/':
            return None
        originals = parse_qs(cover.query).get('fname', [])
        representatives = tuple(item.asset_id for item, image in zip(article.uploads, snapshot.media, strict=True)
                                if originals == [image.source_url])
        location = urlsplit(summary.url)
        if (len(representatives) != 1 or settings.scheduled_at is not None
                or settings.existing_at != summary.listed_at or settings.visibility is not ManagerVisibility.PUBLIC
                or settings.title != snapshot.title or summary.display_title != snapshot.title
                or summary.category != category
                or unquote(location.path) not in (f'/{identity}', f'/entry/{settings.slug}')):
            return None
        content = ReservationContent(snapshot.title, digest, tuple(media), representatives[0],
                                     None if category == '카테고리 없음' else category,
                                     settings.home_topic, tuple(sorted(tags.tags)))
    finally:
        panel.get_by_role('button', name='취소', exact=True).click()
    anonymous_public = False
    with closing(anonymous_context.new_page()) as public:
        response = public.goto(target.identity.url, wait_until='domcontentloaded', timeout=15000)
        location = urlsplit(public.url)
        public_body = public.locator('.tt_article_useless_p_margin')
        title = public.get_by_role('heading', name=snapshot.title, exact=True)
        if (response is not None and response.status == 200 and location.scheme == 'https'
                and location.netloc == blog_host() and not location.query and not location.fragment
                and unquote(location.path) in (f'/{identity}', f'/entry/{settings.slug}')
                and public_body.count() == 1 and title.count() == 1 and title.is_visible()):
            images = public_body.locator('img')
            anonymous_public = (
                ' '.join(public_body.inner_text().split()) == native_text
                and tuple(link.get_attribute('href') for link in public_body.locator('a').all()) == native_links
                and images.count() == 4
                and all((image.get_attribute('src') == expected.source_url
                         or (image.get_attribute('src') == 'https://t1.daumcdn.net/tistory_admin/static/images/pc-image-censoring-v1.gif'
                             and image.get_attribute('data-filename') == expected.filename))
                        and image.get_attribute('alt') == expected.alt
                        for image, expected in zip(images.all(), snapshot.media, strict=True)))
    return ImmediateObservation(SavedIdentity(identity, f'https://{blog_host()}/{identity}'),
                                content, SavedVisibility.PUBLIC, summary.listed_at, now, anonymous_public)
