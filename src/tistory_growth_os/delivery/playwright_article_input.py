from ..site_config import blog_host
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import Page, expect

from .editor_body_fingerprint import article_body_digest
from .editor_correction import OwnedEditor
from .editor_checkpoint import read_editor, record_editor
from .native_article_source import NativeAlt, compose_native_article
from .immediate_execution import ImmediateIntent
from .new_reservation_identity import NewReservationIntent
from .reservation_readback import ReservationContent
from .playwright_editor_mode import select_editor_mode
from .playwright_html_input import HtmlInput, HtmlReplacement, InputResult, LocalUpload, replace_uploaded_html, upload_local_media
from .playwright_observation import UploadedAsset


@dataclass(frozen=True, slots=True)
class ArticleInput:
    intent: NewReservationIntent
    template: str = field(repr=False)
    uploads: tuple[LocalUpload, ...]

    def media(self) -> tuple[NativeAlt, ...]:
        return _media(self.uploads, self.intent.content)

    def valid(self) -> bool:
        return _valid(self.uploads, self.intent.content, self.template)


@dataclass(frozen=True, slots=True)
class ImmediateArticleInput:
    intent: ImmediateIntent
    template: str = field(repr=False)
    uploads: tuple[LocalUpload, ...]

    def media(self) -> tuple[NativeAlt, ...]:
        return _media(self.uploads, self.intent.content)

    def valid(self) -> bool:
        return _valid(self.uploads, self.intent.content, self.template)


def _media(uploads: tuple[LocalUpload, ...], content: ReservationContent) -> tuple[NativeAlt, ...]:
    return tuple(NativeAlt(upload.path.name, image.alt)
                 for upload, image in zip(uploads, content.media, strict=True))


def _valid(uploads: tuple[LocalUpload, ...], content: ReservationContent, template: str) -> bool:
    if (len(uploads) != 4 or len({item.path.name for item in uploads}) != 4
            or tuple(item.asset_id for item in uploads) != tuple(item.asset_id for item in content.media)):
        return False
    if any(item.article_title != content.title or not item.path.is_file()
           or item.path.is_symlink() or item.path.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp')
           or sha256(item.path.read_bytes()).hexdigest() != item.sha256_digest for item in uploads):
        return False
    return article_body_digest(template, _media(uploads, content)) == content.body_digest


def input_new_article(page: Page, request: ArticleInput | ImmediateArticleInput, *, dry_run: bool = True,
                      checkpoint: Callable[[str, tuple[UploadedAsset, ...]], None] | None = None,
                      recovery_path: Path | None = None) -> tuple[UploadedAsset, ...] | None:
    if dry_run or not request.valid():
        return None
    location = urlsplit(page.url)
    if (location.scheme != 'https' or location.netloc != blog_host()
            or location.path.rstrip('/') != '/manage/newpost'):
        return None
    title = page.locator('#post-title-inp')
    body = page.frame_locator('#editor-tistory_ifr').locator('body#tinymce[contenteditable=true]')
    if recovery_path is not None and recovery_path.exists():
        owned = read_editor(recovery_path, request.intent.package_digest, page)
        if (owned.title != request.intent.content.title or owned.body_digest != request.intent.content.body_digest
                or owned.media != request.media()
                or tuple(item.asset_id for item in owned.uploads) != tuple(item.asset_id for item in request.uploads)
                or compose_native_article(request.template, owned.html, request.media()) != owned.html):
            return None
        if checkpoint is not None:
            checkpoint('correction_attempt', owned.uploads)
        if not owned.correct(page):
            return None
        if checkpoint is not None:
            checkpoint('input_verified', owned.uploads)
        return owned.uploads
    if (title.count() != 1 or title.input_value().strip() or body.count() != 1
            or body.inner_text().strip() or body.locator('img').count()):
        return None
    uploaded: list[UploadedAsset] = []

    def record(stage: str) -> None:
        if checkpoint is not None:
            checkpoint(stage, tuple(uploaded))

    record('title_input')
    title.fill(request.intent.content.title)
    for item in request.uploads:
        record('upload_attempt')
        receipt = upload_local_media(page, item, dry_run=False)
        if receipt is None:
            return None
        uploaded.append(receipt)
        record('upload_verified')
    record('html_mode')
    if not select_editor_mode(page, 'HTML', dry_run=False):
        return None
    source = page.locator('#html-editor-container .CodeMirror textarea')
    source.press('ControlOrMeta+A')
    previous = source.input_value()
    record('source_composition')
    compiled = compose_native_article(request.template, previous, request.media())
    if compiled is None:
        return None
    owned = OwnedEditor(request.intent.content.title, compiled, request.intent.content.body_digest,
                        request.media(), tuple(uploaded), request.template)
    if recovery_path is not None:
        record_editor(recovery_path, request.intent.package_digest, owned)
    replacement = HtmlReplacement(HtmlInput(request.intent.content.title, compiled, sha256(compiled.encode()).hexdigest()),
                                  sha256(previous.encode()).hexdigest())
    record('source_replacement')
    if replace_uploaded_html(page, replacement, dry_run=False) is not InputResult.INPUT_VERIFIED:
        return None
    record('basic_mode')
    if not select_editor_mode(page, '기본모드', dry_run=False):
        return None
    record('body_verification')
    if owned.mismatches(page):
        record('correction_attempt')
        if not owned.correct(page):
            record('body_verification')
            return None
        record('correction_verified')
    images = body.locator('img')
    if (title.input_value() != request.intent.content.title or images.count() != 4
            or article_body_digest(body.inner_html(), request.media()) != request.intent.content.body_digest):
        return None
    for image, receipt, expected in zip(images.all(), uploaded, request.media(), strict=True):
        if (image.get_attribute('data-filename') != receipt.filename
                or image.get_attribute('src') != receipt.source_url
                or image.get_attribute('alt') != expected.alt):
            return None
    for paragraph in body.locator('p').all():
        if paragraph.inner_text().strip():
            expect(paragraph).to_be_visible()
            expect(paragraph).to_have_css('font-size', re.compile(r'^(?:1[6-9]|[2-9][0-9])(?:\.[0-9]+)?px$'))
    links = body.locator('a')
    for link in links.all():
        expect(link).to_be_visible()
        expect(link).to_have_css('text-decoration-line', re.compile('underline'))
    if page.url != location.geturl():
        return None
    record('input_verified')
    return tuple(uploaded)
