from contextlib import closing
from pathlib import Path

import pytest
from playwright.sync_api import Route, sync_playwright

from browser_tests.test_native_surface_flow import article_fixture
from tistory_growth_os.delivery import playwright_publish_settings as settings


@pytest.mark.parametrize('case', ['valid', 'dry_run', 'existing', 'origin', 'title', 'current_ignored'])
def test_current_mode_when_a_reviewed_panel_is_ready(case: str, tmp_path: Path) -> None:
    # Given: a reviewed new-editor panel; every request is intercepted locally.
    content = article_fixture(tmp_path).intent.content
    html = '''<textarea id="post-title-inp">검수 제목</textarea>
    <button id="category-btn">생활정보</button>
    <a href="#" aria-label="해안 태그 수정">해안</a>
    <div role="dialog"><legend>발행정보 입력폼</legend>
    <strong class="tit_publish">검수 제목</strong>
    <input id="open20" name="basicSet" value="20" type="radio">
    <dl id="home_subject"><button><span class="mce-txt">국내여행</span></button></dl>
    <button class="btn_date" onclick="document.querySelector('.on').classList.remove('on');this.classList.add('on')">현재</button>
    <button class="btn_date on" onclick="document.body.dataset.reserved='yes'">예약</button>
    <button onclick="document.body.dataset.saved='yes'">공개 발행</button></div>'''
    if case == 'title':
        html = html.replace('검수 제목', '다른 제목')
    if case == 'current_ignored':
        html = html.replace("document.querySelector('.on').classList.remove('on');this.classList.add('on')", '')
    requests: list[str] = []

    def serve(route: Route) -> None:
        requests.append(route.request.method)
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        _ = page.route('**/*', serve)
        origin = 'https://example.test' if case == 'origin' else 'https://example.tistory.com'
        suffix = '/93' if case == 'existing' else ''
        _ = page.goto(origin + '/manage/newpost' + suffix)
        # When: selecting current-time public mode, without submitting.
        result = settings.configure_immediate_publication(page, content, dry_run=case == 'dry_run')
        # Then: only a matching, responsive new panel can be input-verified.
        expected = 'input_verified' if case == 'valid' else 'dry_run' if case == 'dry_run' else 'blocked'
        assert result == expected
        if case == 'valid':
            assert page.locator('.btn_date.on').inner_text() == '현재'
            assert page.locator('#open20').is_checked()
        assert page.locator('body').get_attribute('data-reserved') is None
        assert page.locator('body').get_attribute('data-saved') is None
        assert requests == ['GET']
