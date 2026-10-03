from ..site_config import blog_host
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page

from ..domain.ids import PostId
from .editor_body_fingerprint import article_body_digest
from .new_reservation_identity import NewReservationIntent, SavedIdentity
from .playwright_article_input import ArticleInput, input_new_article
from .playwright_editor_readback import read_editor_tags
from .playwright_manager import read_manager_inventory, read_manager_post
from .playwright_observation import UploadedAsset, structural_reservation_observation
from .playwright_publish_settings import configure_new_reservation
from .playwright_saved_reservation import read_saved_reservation
from .reservation_readback import KST, ReservationObservation, ReservationTarget


class NativePreparationError(RuntimeError):
    pass


@dataclass
class NativeSurface:
    page: Page = field(repr=False)
    article: ArticleInput = field(repr=False)
    stop: Callable[[], bool] = field(repr=False)
    authority: Callable[[NewReservationIntent, datetime], tuple[str, ...]] | None = field(default=None, repr=False)
    prior: frozenset[PostId] | None = None
    uploads: tuple[UploadedAsset, ...] = field(default=(), repr=False)
    prepared: bool = False
    save_attempted: bool = False
    phase: str = 'created'
    checkpoint: Callable[[str, tuple[UploadedAsset, ...]], None] | None = field(default=None, repr=False)
    preserve_editor: bool = False

    def _input_checkpoint(self, stage: str, uploads: tuple[UploadedAsset, ...]) -> None:
        self.phase = 'article_input/' + stage
        self.uploads = uploads
        if self.checkpoint is not None:
            self.checkpoint(self.phase, uploads)

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def stopped(self) -> bool:
        return self.stop()

    def authorize(self, request: NewReservationIntent, now: datetime) -> tuple[str, ...]:
        if self.authority is None:
            return ('runtime_authority_required',)
        if request != self.article.intent or not self.article.valid():
            return ('package_changed',)
        return self.authority(request, now)

    def inventory(self) -> frozenset[PostId] | None:
        self.phase = 'inventory'
        if self.preserve_editor:
            with closing(self.page.context.new_page()) as reader:
                _ = reader.goto(f'https://{blog_host()}/manage/posts/', wait_until='domcontentloaded')
                reader.locator('#mArticle input[id^="inpCheck"]').first.wait_for(state='attached', timeout=10000)
                self.prior = read_manager_inventory(reader)
        else:
            self.prior = read_manager_inventory(self.page)
        return self.prior

    def preparation_fingerprint(self) -> str | None:
        request = self.article.intent
        location = urlsplit(self.page.url)
        if (location.scheme != 'https' or location.netloc != blog_host()
                or location.path.rstrip('/') != '/manage/newpost' or not self.article.valid()):
            return None
        body = self.page.frame_locator('#editor-tistory_ifr').locator('body#tinymce[contenteditable=true]')
        if body.count() != 1 or not body.is_visible() or body.locator('img').count() != 4:
            return None
        if not self.uploads:
            restored: list[UploadedAsset] = []
            for image, expected in zip(body.locator('img').all(), self.article.uploads, strict=True):
                source = image.get_attribute('src') or ''
                if image.get_attribute('data-filename') != expected.path.name or urlsplit(source).scheme != 'https':
                    return None
                restored.append(UploadedAsset(expected.asset_id, source, expected.path.name))
            self.uploads = tuple(restored)
        panel = self.page.get_by_role('dialog').filter(has=self.page.locator('legend').filter(has_text='발행정보 입력폼'))
        if not panel.is_visible():
            self.page.locator('#publish-layer-btn').click()
        if not self._preflight(request):
            return None
        self.prepared = True
        return sha256(json.dumps([request.package_digest,
            [(item.asset_id, item.filename, item.source_url) for item in self.uploads]],
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

    def prepare(self, request: NewReservationIntent) -> None:
        if self.stopped() or self.authorize(request, self.now()) or self.prior is None or self.prepared:
            raise NativePreparationError('prepare_boundary')
        self.phase = 'article_input'
        _ = self.page.goto(f'https://{blog_host()}/manage/newpost', wait_until='domcontentloaded')
        self.page.locator('#post-title-inp').wait_for(state='visible', timeout=10000)
        self.page.frame_locator('#editor-tistory_ifr').locator('#tinymce').wait_for(timeout=10000)
        uploads = input_new_article(self.page, self.article, dry_run=False, checkpoint=self._input_checkpoint)
        if uploads is None:
            raise NativePreparationError('article_input_unverified')
        self.uploads = uploads
        self.phase = 'reservation_settings'
        if configure_new_reservation(self.page, request, dry_run=False) != 'input_verified':
            raise NativePreparationError('settings_unverified')
        self.phase = 'final_preflight'
        self.prepared = self._preflight(request)
        if not self.prepared:
            raise NativePreparationError('final_preflight_failed')

    def _preflight(self, request: NewReservationIntent) -> bool:
        location = urlsplit(self.page.url)
        if (location.scheme != 'https' or location.netloc != blog_host()
                or location.path.rstrip('/') != '/manage/newpost' or len(self.uploads) != 4):
            return False
        body = self.page.frame_locator('#editor-tistory_ifr').locator('body#tinymce[contenteditable=true]')
        if article_body_digest(body.inner_html(), self.article.media()) != request.content.body_digest:
            return False
        images = body.locator('img')
        if images.count() != 4:
            return False
        for image, upload in zip(images.all(), self.uploads, strict=True):
            if image.get_attribute('src') != upload.source_url or image.get_attribute('data-filename') != upload.filename:
                return False
        panel = self.page.get_by_role('dialog').filter(has=self.page.locator('legend').filter(has_text='발행정보 입력폼'))
        if panel.count() != 1 or not panel.is_visible():
            return False
        stamp = request.scheduled_at.astimezone(KST)
        expected_category = request.content.category or '카테고리 없음'
        observed_tags = tuple(sorted(text.removeprefix('#').strip() for text in self.page.get_by_role('link', name=re.compile(r'(?:^| )태그 수정$'), include_hidden=True).all_inner_texts()))
        if (self.page.locator('#post-title-inp').input_value() != request.content.title
                or panel.locator('.tit_publish').inner_text().strip() != request.content.title
                or self.page.locator('#category-btn').inner_text().replace('더보기', '').strip() != expected_category
                or observed_tags != tuple(sorted(request.content.tags))
                or not panel.locator('#open20').is_checked()
                or panel.locator('.btn_date.on').inner_text().strip() != '예약'
                or panel.locator('button.btn_reserve').inner_text().strip() != stamp.strftime('%Y-%m-%d')
                or panel.locator('#dateHour').input_value() != stamp.strftime('%H')
                or panel.locator('#dateMinute').input_value() != stamp.strftime('%M')
                or panel.locator('#home_subject button .mce-txt').inner_text().strip() != request.content.home_topic):
            return False
        thumbnail = panel.locator('.thumb_g')
        if thumbnail.count() != 1:
            return False
        match = re.fullmatch(r'background-image: url\("([^"\r\n]+)"\);', thumbnail.get_attribute('style') or '')
        if match is None:
            return False
        image_url = urlsplit(match.group(1))
        covers = tuple(item for item in self.uploads if item.asset_id == request.content.representative)
        return (len(covers) == 1 and image_url.scheme == 'https' and image_url.netloc == 'img1.daumcdn.net'
                and image_url.path == '/thumb/C170x170/'
                and parse_qs(image_url.query).get('fname') == [covers[0].source_url])

    def save(self, request: NewReservationIntent) -> SavedIdentity | None:
        self.phase = 'save_preflight'
        if (not self.prepared or self.save_attempted or self.prior is None or self.stopped()
                or self.now() >= request.scheduled_at or self.authorize(request, self.now())
                or not self._preflight(request)):
            return None
        panel = self.page.get_by_role('dialog').filter(has=self.page.locator('legend').filter(has_text='발행정보 입력폼'))
        button = panel.get_by_role('button', name=re.compile(r'^공개\s*발행$'))
        if button.count() != 1 or not button.is_enabled():
            return None
        self.save_attempted = True
        self.phase = 'save_clicked'
        button.click(timeout=10000)
        self.page.wait_for_url(re.compile(rf'https://{re.escape(blog_host())}/manage/posts/?(?:\?.*)?$'), timeout=15000)
        observed = read_manager_inventory(self.page)
        self.phase = 'save_identity'
        if observed is None or not self.prior.issubset(observed) or len(observed - self.prior) != 1:
            return None
        identity = next(iter(observed - self.prior))
        _ = self.page.goto(f'https://{blog_host()}/manage/posts/', wait_until='domcontentloaded')
        self.page.locator(f'#inpCheck{identity}').wait_for(state='attached', timeout=10000)
        summary = read_manager_post(self.page, identity)
        if (summary is None or not summary.reserved or summary.listed_at != request.scheduled_at
                or summary.display_title.removeprefix('[예약]').lstrip() != request.content.title):
            return None
        return SavedIdentity(identity, f'https://{blog_host()}/{identity}')

    def readback(self, target: ReservationTarget) -> ReservationObservation | None:
        self.phase = 'saved_readback'
        _ = self.page.goto(f'https://{blog_host()}/manage/posts/', wait_until='domcontentloaded')
        self.page.locator(f'#inpCheck{target.post_id}').wait_for(state='attached', timeout=10000)
        summary = read_manager_post(self.page, target.post_id)
        if summary is None:
            return None
        _ = self.page.goto(f'https://{blog_host()}/manage/newpost/{target.post_id}', wait_until='domcontentloaded')
        self.page.locator('#post-title-inp').wait_for(state='visible', timeout=10000)
        self.page.frame_locator('#editor-tistory_ifr').locator('#tinymce').wait_for(timeout=10000)
        tags = read_editor_tags(self.page, target.post_id)
        self.page.locator('#publish-layer-btn').click()
        snapshot = read_saved_reservation(self.page, summary, tags)
        panel = self.page.get_by_role('dialog').filter(has=self.page.locator('legend').filter(has_text='발행정보 입력폼'))
        panel.get_by_role('button', name='취소', exact=True).click()
        return None if snapshot is None else structural_reservation_observation(snapshot, self.uploads, self.article.media(), self.now())
