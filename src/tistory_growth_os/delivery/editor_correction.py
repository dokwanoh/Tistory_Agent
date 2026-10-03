from ..site_config import blog_host
from dataclasses import dataclass, field
from hashlib import sha256
from urllib.parse import urlsplit

from playwright.sync_api import Page

from .editor_body_fingerprint import article_body_digest
from .native_article_source import NativeAlt
from .playwright_editor_mode import select_editor_mode
from .playwright_html_input import HtmlInput, HtmlReplacement, InputResult, replace_uploaded_html
from .playwright_observation import UploadedAsset


@dataclass(frozen=True, slots=True)
class OwnedEditor:
    title: str
    html: str = field(repr=False)
    body_digest: str
    media: tuple[NativeAlt, ...]
    uploads: tuple[UploadedAsset, ...] = field(repr=False)
    template: str = field(default='', repr=False)

    def mismatches(self, page: Page) -> tuple[str, ...]:
        body = page.frame_locator('#editor-tistory_ifr').locator('body#tinymce[contenteditable=true]')
        result: list[str] = []
        if page.locator('#post-title-inp').input_value() != self.title:
            result.append('title')
        if article_body_digest(body.inner_html(), self.media) != self.body_digest:
            result.append('body')
        images = body.locator('img')
        if images.count() != 4:
            result.append('media')
        else:
            for image, upload, alt in zip(images.all(), self.uploads, self.media, strict=True):
                if (image.get_attribute('src') != upload.source_url
                        or image.get_attribute('data-filename') != upload.filename
                        or image.get_attribute('alt') != alt.alt):
                    result.append('media')
                    break
        return tuple(result)

    def recognizes(self, page: Page) -> bool:
        location = urlsplit(page.url)
        if (location.scheme != 'https' or location.netloc != blog_host()
                or location.path.rstrip('/') != '/manage/newpost' or len(self.uploads) != 4):
            return False
        images = page.frame_locator('#editor-tistory_ifr').locator('body#tinymce img')
        observed = {(image.get_attribute('src'), image.get_attribute('data-filename')) for image in images.all()}
        expected = {(item.source_url, item.filename) for item in self.uploads}
        return len(observed & expected) >= 3 and images.count() <= 4

    def correct(self, page: Page) -> bool:
        if not self.recognizes(page):
            return False
        defects = self.mismatches(page)
        if 'title' in defects:
            page.locator('#post-title-inp').fill(self.title)
        if 'body' in defects or 'media' in defects:
            if not select_editor_mode(page, 'HTML', dry_run=False):
                return False
            source = page.locator('#html-editor-container .CodeMirror textarea')
            source.press('ControlOrMeta+A')
            replacement = HtmlReplacement(HtmlInput(self.title, self.html, sha256(self.html.encode()).hexdigest()),
                                          sha256(source.input_value().encode()).hexdigest())
            if replace_uploaded_html(page, replacement, dry_run=False) is not InputResult.INPUT_VERIFIED:
                return False
            if not select_editor_mode(page, '기본모드', dry_run=False):
                return False
        return not self.mismatches(page)
