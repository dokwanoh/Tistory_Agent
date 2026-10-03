from contextlib import closing

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery.playwright_editor_mode import select_editor_mode


@pytest.mark.parametrize('case', ['valid', 'unexpected_dialog', 'existing_post', 'dry_run'])
def test_mode_confirmation_is_narrow_and_never_saves(case: str) -> None:
    message = '정말 삭제하시겠습니까?' if case == 'unexpected_dialog' else '작성 모드를 변경하시겠습니까?\n현재 서식이 유지되지 않을 수 있습니다.'
    html = '''<button id="editor-mode-layer-btn">기본모드</button>
    <button role="menuitem" onclick="if(confirm(document.querySelector('pre').textContent)){document.querySelector('#html-editor-container').hidden=false}">HTML</button>
    <pre></pre><div id="html-editor-container" hidden><div class="CodeMirror"><textarea></textarea></div></div>'''

    def serve(route: Route) -> None:
        route.fulfill(content_type='text/html; charset=utf-8', body=html.replace('<pre></pre>', '<pre>' + message + '</pre>'))

    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        _ = page.route('**/*', serve)
        _ = page.goto('https://example.tistory.com/manage/newpost' + ('/92' if case == 'existing_post' else ''))
        result = select_editor_mode(page, 'HTML', dry_run=case == 'dry_run', timeout_ms=300)
        assert result is (case == 'valid')
        assert page.locator('#html-editor-container').is_visible() is (case == 'valid')


def test_basic_mode_uses_visible_html_toolbar_instead_of_hidden_original() -> None:
    # Given: HTML mode hides TinyMCE's original trigger and provides its own native menu.
    html = '''<button id="editor-mode-layer-btn" hidden>기본모드</button>
    <button onclick="document.querySelector('[role=menuitem]').hidden=false"><i>HTML</i><i>더보기</i></button>
    <div role="menuitem" hidden onclick="document.querySelector('iframe').hidden=false;document.querySelector('#html-editor-container').hidden=true">기본모드</div>
    <div id="html-editor-container"><div class="CodeMirror"><textarea></textarea></div></div>
    <iframe id="editor-tistory_ifr" hidden srcdoc='<body id="tinymce" contenteditable="true">검수 본문</body>'></iframe>'''

    def serve(route: Route) -> None:
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        _ = page.route('**/*', serve)
        _ = page.goto('https://example.tistory.com/manage/newpost')
        # When: the adapter returns to the basic editor through normal controls.
        result = select_editor_mode(page, '기본모드', dry_run=False, timeout_ms=300)
        # Then: the original content is visible without saving or changing it.
        assert result is True
        assert page.frame_locator('#editor-tistory_ifr').locator('#tinymce').inner_text() == '검수 본문'
        assert not page.locator('#html-editor-container').is_visible()
