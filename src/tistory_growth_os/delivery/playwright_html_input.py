from ..site_config import blog_host
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import Page, expect

from ..domain.ids import MediaId
from .playwright_observation import UploadedAsset


@dataclass(frozen=True, slots=True)
class HtmlInput:
    title: str
    html: str = field(repr=False)
    body_sha256: str


class InputResult(StrEnum):
    DRY_RUN = 'dry_run'
    BLOCKED = 'blocked'
    INPUT_VERIFIED = 'input_verified'
    UNKNOWN = 'unknown'


@dataclass(frozen=True, slots=True)
class HtmlReplacement:
    content: HtmlInput
    previous_sha256: str


def replace_uploaded_html(page: Page, request: HtmlReplacement, *, dry_run: bool = True) -> InputResult:
    if dry_run:
        return InputResult.DRY_RUN
    location = urlsplit(page.url)
    content = request.content
    title = page.locator('#post-title-inp')
    editor = page.locator('#html-editor-container .CodeMirror')
    source = editor.locator('textarea')
    if (location.scheme != 'https' or location.netloc != blog_host()
            or location.path.rstrip('/') != '/manage/newpost'
            or not content.title.strip() or title.count() != 1 or title.input_value() != content.title
            or editor.count() != 1 or not editor.is_visible() or source.count() != 1
            or not content.html.strip() or sha256(content.html.encode()).hexdigest() != content.body_sha256):
        return InputResult.BLOCKED
    source.press('ControlOrMeta+A')
    if sha256(source.input_value().encode()).hexdigest() != request.previous_sha256:
        return InputResult.BLOCKED
    page.keyboard.insert_text(content.html)
    source.press('ControlOrMeta+A')
    if (source.input_value() != content.html or title.input_value() != content.title
            or page.url != location.geturl()):
        return InputResult.UNKNOWN
    return InputResult.INPUT_VERIFIED


@dataclass(frozen=True, slots=True)
class LocalUpload:
    asset_id: MediaId
    path: Path
    sha256_digest: str
    article_title: str


def upload_local_media(page: Page, request: LocalUpload, *, dry_run: bool = True) -> UploadedAsset | None:
    if dry_run:
        return None
    location = urlsplit(page.url)
    if (location.scheme != 'https' or location.netloc != blog_host()
            or location.path.rstrip('/') != '/manage/newpost'
            or not request.asset_id.strip() or not request.path.is_file()
            or request.path.is_symlink()
            or request.path.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp')
            or sha256(request.path.read_bytes()).hexdigest() != request.sha256_digest):
        return None
    title = page.locator('#post-title-inp')
    if (not request.article_title.strip() or title.count() != 1
            or title.input_value() != request.article_title):
        return None
    body = page.frame_locator('#editor-tistory_ifr').locator('body#tinymce[contenteditable=true]')
    if body.count() != 1:
        return None
    images = body.locator('img')
    before = images.count()
    if before >= 4 or any(image.get_attribute('data-filename') == request.path.name for image in images.all()):
        return None
    body.click()
    body.press('Meta+ArrowDown')
    body.press('ArrowRight')
    page.get_by_role('button', name='첨부', exact=True).click()
    with page.expect_file_chooser(timeout=5000) as selection:
        page.get_by_role('menuitem', name='사진', exact=True).click()
    selection.value.set_files(request.path.resolve(), timeout=10000)
    expect(images).to_have_count(before + 1, timeout=15000)
    uploaded = images.nth(before)
    expect(uploaded).to_have_attribute('data-filename', request.path.name, timeout=15000)
    expect(uploaded).to_have_attribute('src', re.compile(r'^https://'), timeout=15000)
    source = uploaded.get_attribute('src')
    if (uploaded.get_attribute('data-filename') != request.path.name or not source
            or urlsplit(source).scheme != 'https'
            or urlsplit(page.url).path.rstrip('/') != '/manage/newpost'):
        return None
    return UploadedAsset(request.asset_id, source, request.path.name)


def fill_blank_html_editor(page: Page, request: HtmlInput, *, dry_run: bool = True) -> InputResult:
    if dry_run:
        return InputResult.DRY_RUN
    original_url = page.url
    url = urlsplit(original_url)
    if (url.scheme != 'https' or url.netloc != blog_host()
            or url.path.rstrip('/') != '/manage/newpost'
            or not request.title.strip() or not request.html.strip()
            or sha256(request.html.encode()).hexdigest() != request.body_sha256):
        return InputResult.BLOCKED
    title = page.locator('#post-title-inp')
    editor = page.locator('#html-editor-container .CodeMirror')
    source = editor.locator('textarea')
    if (title.count() != 1 or not title.is_visible() or title.input_value().strip()
            or editor.count() != 1 or not editor.is_visible() or source.count() != 1):
        return InputResult.BLOCKED
    source.press('ControlOrMeta+A', timeout=3000)
    initial = source.input_value(timeout=3000).strip()
    if (initial not in ('', '<p data-ke-size="size16"></p>')
            or title.input_value().strip() or page.url != original_url):
        return InputResult.BLOCKED
    title.fill(request.title, timeout=3000)
    source.press('ControlOrMeta+A', timeout=3000)
    page.keyboard.insert_text(request.html)
    source.press('ControlOrMeta+A', timeout=3000)
    if (page.url != original_url or title.input_value() != request.title
            or source.input_value(timeout=3000) != request.html):
        return InputResult.UNKNOWN
    return InputResult.INPUT_VERIFIED
