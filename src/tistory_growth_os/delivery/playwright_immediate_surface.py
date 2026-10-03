from ..site_config import blog_host
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import BrowserContext, Page

from ..domain.ids import PostId
from .editor_body_fingerprint import article_body_digest
from .editor_correction import OwnedEditor
from .immediate_execution import ImmediateIntent
from .immediate_media import MediaBinding, media_bindings
from .immediate_readback import ImmediateObservation, ImmediateTarget
from .new_reservation_identity import SavedIdentity
from .playwright_article_input import ImmediateArticleInput, input_new_article
from .playwright_immediate_observation import immediate_observation
from .playwright_manager import ManagerVisibility, read_manager_inventory, read_manager_post
from .playwright_native_surface import NativePreparationError
from .playwright_observation import UploadedAsset
from .playwright_publish_settings import configure_immediate_publication, configure_publish_panel


@dataclass(slots=True)  # noqa: MUTABLE_OK
class ImmediateNativeSurface:
    """Own one mutable native-editor attempt; never retries an uncertain final save."""

    page: Page = field(repr=False)
    anonymous_context: BrowserContext = field(repr=False)
    article: ImmediateArticleInput = field(repr=False)
    stop: Path = field(repr=False)
    authority: Callable[[ImmediateIntent, datetime], tuple[str, ...]] = field(repr=False)
    checkpoint: Callable[[str, tuple[UploadedAsset, ...]], None] | None = field(default=None, repr=False)
    prior: frozenset[PostId] | None = None
    uploads: tuple[UploadedAsset, ...] = field(default=(), repr=False)
    bindings: tuple[MediaBinding, ...] = field(default=(), repr=False)
    prepared: bool = False
    save_attempted: bool = False
    phase: str = 'created'
    recovery_path: Path | None = field(default=None, repr=False)
    editor: OwnedEditor | None = field(default=None, repr=False)

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def stopped(self) -> bool:
        return self.stop.exists()

    def authorize(self, request: ImmediateIntent, now: datetime) -> tuple[str, ...]:
        if request != self.article.intent or not self.article.valid():
            return ('package_changed',)
        return self.authority(request, now)

    def inventory(self) -> frozenset[PostId] | None:
        self.phase = 'inventory'
        if self.recovery_path is not None and self.recovery_path.exists():
            manager = self.page.context.new_page()
            try:
                _ = manager.goto(f'https://{blog_host()}/manage/posts/', wait_until='domcontentloaded')
                self.prior = read_manager_inventory(manager)
                return self.prior
            finally:
                manager.close()
        self.prior = read_manager_inventory(self.page)
        return self.prior

    def _checkpoint(self, stage: str, uploads: tuple[UploadedAsset, ...]) -> None:
        self.phase = 'article_input/' + stage
        self.uploads = uploads
        self.bindings = media_bindings(uploads)
        if stage == 'basic_mode':
            source = self.page.locator('#html-editor-container .CodeMirror textarea')
            source.press('ControlOrMeta+A')
            self.editor = OwnedEditor(self.article.intent.content.title, source.input_value(),
                self.article.intent.content.body_digest, self.article.media(), uploads, self.article.template)
        if self.checkpoint is not None:
            self.checkpoint(self.phase, uploads)
        if self.stopped():
            raise NativePreparationError('kill_switch')

    def prepare(self, request: ImmediateIntent) -> None:
        if self.stopped() or self.authorize(request, self.now()) or self.prior is None or self.prepared:
            raise NativePreparationError('prepare_boundary')
        self.phase = 'article_input'
        if self.recovery_path is None or not self.recovery_path.exists():
            _ = self.page.goto(f'https://{blog_host()}/manage/newpost', wait_until='domcontentloaded')
        else:
            self._close_panel()
        self.page.locator('#post-title-inp').wait_for(state='visible', timeout=10000)
        self.page.frame_locator('#editor-tistory_ifr').locator('#tinymce').wait_for(timeout=10000)
        uploads = input_new_article(self.page, self.article, dry_run=False, checkpoint=self._checkpoint,
                                    recovery_path=self.recovery_path)
        if uploads is None:
            raise NativePreparationError('article_input_unverified')
        self.uploads = uploads
        self.phase = 'immediate_settings'
        if (not configure_publish_panel(self.page, request.content)
                or configure_immediate_publication(self.page, request.content, dry_run=False) != 'input_verified'):
            raise NativePreparationError('settings_unverified')
        self.phase = 'final_preflight'
        self.prepared = self._preflight(request) or self._correct_preflight(request)
        if not self.prepared:
            raise NativePreparationError('final_preflight_failed')

    def _close_panel(self) -> None:
        panel = self.page.get_by_role('dialog').filter(has=self.page.locator('legend').filter(has_text='발행정보 입력폼'))
        if panel.count() == 1 and panel.is_visible():
            panel.get_by_role('button', name='취소', exact=True).click()

    def _correct_preflight(self, request: ImmediateIntent) -> bool:
        if (self.save_attempted or self.stopped() or self.authorize(request, self.now())
                or self.recovery_path is None or not self.recovery_path.exists()):
            return False
        self._close_panel()
        if self.editor is None or not self.editor.correct(self.page):
            return False
        return (configure_publish_panel(self.page, request.content)
                and configure_immediate_publication(self.page, request.content, dry_run=False) == 'input_verified'
                and self._preflight(request))

    def _preflight(self, request: ImmediateIntent) -> bool:
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
        observed_tags = tuple(sorted(text.removeprefix('#').strip() for text in self.page.get_by_role(
            'link', name=re.compile(r'(?:^| )태그 수정$'), include_hidden=True).all_inner_texts()))
        if (self.page.locator('#post-title-inp').input_value() != request.content.title
                or panel.locator('.tit_publish').inner_text().strip() != request.content.title
                or self.page.locator('#category-btn').inner_text().replace('더보기', '').strip() != (request.content.category or '카테고리 없음')
                or observed_tags != tuple(sorted(request.content.tags))
                or not panel.locator('#open20').is_checked()
                or panel.locator('.btn_date.on').inner_text().strip() != '현재'
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

    def save(self, request: ImmediateIntent) -> SavedIdentity | None:
        self.phase = 'save_preflight'
        if (not self.prepared or self.save_attempted or self.prior is None or self.stopped()
                or self.now() >= request.valid_until or self.authorize(request, self.now())
                or not (self._preflight(request) or self._correct_preflight(request))):
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
        if (summary is None or summary.reserved or summary.visibility is not ManagerVisibility.PUBLIC
                or summary.display_title != request.content.title):
            return None
        return SavedIdentity(identity, f'https://{blog_host()}/{identity}')

    def readback(self, target: ImmediateTarget) -> ImmediateObservation | None:
        self.phase = 'saved_and_anonymous_readback'
        observed = immediate_observation(self.page, self.anonymous_context, self.article, target, self.now(), self.bindings)
        if observed is not None:
            _ = self.page.goto(f'https://{blog_host()}/manage/posts/', wait_until='domcontentloaded')
            self.page.locator(f'#inpCheck{target.identity.post_id}').wait_for(state='attached', timeout=10000)
        return observed
