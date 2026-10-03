from ..site_config import blog_host
import re
from typing import Literal
from urllib.parse import urlsplit

from playwright.sync_api import Dialog, Page, TimeoutError as PlaywrightTimeout, expect


def select_editor_mode(
    page: Page, mode: Literal['HTML', '기본모드'], *, dry_run: bool = True, timeout_ms: int = 5000,
) -> bool:
    if dry_run:
        return False
    location = urlsplit(page.url)
    if (location.scheme != 'https' or location.netloc != blog_host()
            or location.path.rstrip('/') != '/manage/newpost'):
        return False
    rejected: list[str] = []

    def confirm(dialog: Dialog) -> None:
        if (dialog.type == 'confirm' and dialog.message.replace('\r\n', '\n').strip()
                == '작성 모드를 변경하시겠습니까?\n현재 서식이 유지되지 않을 수 있습니다.'):
            dialog.accept()
        else:
            rejected.append('unexpected_dialog')
            dialog.dismiss()

    page.on('dialog', confirm)
    try:
        trigger = page.locator('#editor-mode-layer-btn').filter(visible=True)
        if trigger.count() == 0:
            trigger = page.locator('button').filter(has_text=re.compile(r'^HTML\s*더보기$')).filter(visible=True)
        if trigger.count() != 1:
            return False
        trigger.click(timeout=timeout_ms)
        page.get_by_role('menuitem', name=mode, exact=True).filter(visible=True).click(timeout=timeout_ms)
        if rejected:
            return False
        surface = (page.locator('#html-editor-container .CodeMirror') if mode == 'HTML'
                   else page.frame_locator('#editor-tistory_ifr').locator('body#tinymce[contenteditable=true]'))
        expect(surface).to_be_visible(timeout=timeout_ms)
        return not rejected and page.url == location.geturl()
    except (PlaywrightTimeout, AssertionError):
        return False
    finally:
        page.remove_listener('dialog', confirm)
