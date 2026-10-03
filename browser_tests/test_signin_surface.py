from contextlib import closing

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery.browser_signin import SignInState
from tistory_growth_os.delivery.playwright_signin import PlaywrightSignIn, reconnect_manager


@pytest.mark.parametrize('url,html,expected', [
    ('https://accounts.kakao.com/login', '<h2>로그인할 카카오계정 선택</h2><button>owner@example.test홍길동</button>', SignInState.ACCOUNT),
    ('https://accounts.kakao.com/login', '<h2>로그인할 카카오계정 선택</h2><button>owner@example.test.evil</button>', SignInState.UNKNOWN),
    ('https://accounts.kakao.com/login', '<h2>로그인할 카카오계정 선택</h2><button>owner@example.test홍길동</button><input type="password">', SignInState.OWNER_REQUIRED),
    ('https://accounts.kakao.com/login', '<h2>추가 인증</h2><button>owner@example.test홍길동</button>', SignInState.OWNER_REQUIRED),
    ('https://evil.invalid/auth/login', '<button>카카오계정으로 로그인</button>', SignInState.UNKNOWN),
    ('https://example.tistory.com/manage/posts/', '<h2>티스토리 관리센터 본문</h2>', SignInState.READY),
    ('https://example.tistory.com/manage/posts/', '<h2 style="width:0;height:0;overflow:hidden">티스토리 관리센터 본문</h2>', SignInState.READY),
    ('https://example.tistory.com/entry/example', '<h2>티스토리 관리센터 본문</h2>', SignInState.UNKNOWN),
])
def test_observed_page_is_classified_without_secret_reads(url: str, html: str, expected: SignInState) -> None:
    def serve(route: Route) -> None:
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as playwright, closing(playwright.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        page.route('**/*', serve)
        page.goto(url)
        assert PlaywrightSignIn(page, 'owner@example.test').observe() == expected


def test_normal_flow_runs_in_real_browser_without_network() -> None:
    def serve(route: Route) -> None:
        if route.request.url == 'https://www.tistory.com/auth/login':
            html = '<button onclick="location.href=\'https://accounts.kakao.com/login\'">카카오계정으로 로그인</button>'
        elif route.request.url == 'https://accounts.kakao.com/login':
            html = '<h2>로그인할 카카오계정 선택</h2><button onclick="location.href=\'https://example.tistory.com/manage/posts/\'">owner@example.test홍길동</button>'
        else:
            html = '<h2 style="width:0;height:0;overflow:hidden">티스토리 관리센터 본문</h2>'
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as playwright, closing(playwright.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        page.route('**/*', serve)
        page.goto('https://www.tistory.com/auth/login')
        assert reconnect_manager(PlaywrightSignIn(page, 'owner@example.test')) == SignInState.READY
