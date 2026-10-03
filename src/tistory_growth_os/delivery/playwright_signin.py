from ..site_config import blog_host
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from playwright.sync_api import Locator, Page, TimeoutError as BrowserTimeout

from .browser_signin import SignInState, connect_manager


@dataclass(frozen=True, slots=True)
class PlaywrightSignIn:
    page: Page
    account_identifier: str

    def account_button(self) -> Locator:
        return self.page.get_by_role('button').filter(
            has_text=re.compile(r'^' + re.escape(self.account_identifier) + r'(?:\s|[^\w@.+-]|$)')
        )

    def observe(self) -> SignInState:
        url = urlsplit(self.page.url)
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443):
            return SignInState.UNKNOWN
        if self.page.locator('input[type=password]:visible').count():
            return SignInState.OWNER_REQUIRED
        if url.hostname == blog_host() and url.path.rstrip('/') == '/manage/posts':
            if self.page.get_by_role('heading', name='티스토리 관리센터 본문', exact=True).count() == 1:
                return SignInState.READY
        if url.hostname == 'www.tistory.com' and url.path == '/auth/login':
            if self.page.get_by_text('카카오계정으로 로그인', exact=True).count() == 1:
                return SignInState.LOGIN
        if url.hostname == 'accounts.kakao.com':
            if not self.page.get_by_role('heading', name='로그인할 카카오계정 선택', exact=True).is_visible():
                return SignInState.OWNER_REQUIRED
            if self.account_identifier and self.account_button().count() == 1:
                return SignInState.ACCOUNT
        return SignInState.UNKNOWN

    def open_login(self) -> None:
        if self.observe() != SignInState.LOGIN:
            return
        self.page.get_by_text('카카오계정으로 로그인', exact=True).click(timeout=10000)
        self.page.wait_for_url('https://accounts.kakao.com/**', timeout=15000)
        self.page.get_by_role('heading').first.wait_for(state='visible', timeout=10000)

    def choose_account(self) -> None:
        if self.observe() != SignInState.ACCOUNT:
            return
        self.account_button().click(timeout=10000)
        self.page.wait_for_url(f'https://{blog_host()}/manage/posts/**', timeout=15000)
        self.page.get_by_role('heading', name='티스토리 관리센터 본문', exact=True).wait_for(
            state='attached', timeout=10000
        )


def reconnect_manager(surface: PlaywrightSignIn) -> SignInState:
    try:
        return connect_manager(surface)
    except BrowserTimeout:
        return SignInState.UNKNOWN
