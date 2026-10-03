from contextlib import closing
from datetime import datetime

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery.playwright_manager import read_manager_post, ManagerVisibility
from tistory_growth_os.domain.ids import PostId


def row_html() -> str:
    return '''<li><input id="inpCheck79" type="checkbox">
    <a class="link_cont" href="https://example.tistory.com/entry/fixture">[예약] 시험 제목</a>
    <span class="txt_cate txt_ellip">스포츠</span>
    <span class="txt_info txt_ellip">fixture-owner</span>
    <span class="txt_info">2030-01-01 12:00</span>
    <button class="btn_opt"><span class="txt_ellip">공개</span></button>
    <label><span class="txt_set txt_ellip">비공개</span></label></li>'''


@pytest.mark.parametrize('visibility', ['공개', '비공개', '보호'])
def test_manager_row_returns_observed_fields_without_writes(visibility: str) -> None:
    requests: list[str] = []

    def serve(route: Route) -> None:
        requests.append(route.request.method)
        html = '<h2>티스토리 관리센터 본문</h2><ul>' + row_html().replace('>공개<', f'>{visibility}<') + '</ul>'
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as p, closing(p.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        page.route('**/*', serve)
        page.goto('https://example.tistory.com/manage/posts/')
        result = read_manager_post(page, PostId('79'))
        assert result is not None
        assert result.post_id == PostId('79')
        assert result.display_title == '[예약] 시험 제목'
        assert result.url == 'https://example.tistory.com/entry/fixture'
        assert result.listed_at == datetime.fromisoformat('2030-01-01T12:00:00+09:00')
        assert result.category == '스포츠'
        assert result.visibility is {'공개': ManagerVisibility.PUBLIC, '비공개': ManagerVisibility.PRIVATE, '보호': ManagerVisibility.PROTECTED}[visibility]
        assert requests == ['GET']


@pytest.mark.parametrize('case', ['origin', 'login', 'missing', 'duplicate', 'date', 'foreign_url', 'visibility', 'missing_heading', 'unsafe_id'])
def test_unknown_or_ambiguous_manager_surface_never_returns_a_post(case: str) -> None:
    html = '<h2>티스토리 관리센터 본문</h2><ul>' + row_html() + '</ul>'
    variants = {
        'missing': html.replace('inpCheck79', 'inpCheck80'),
        'duplicate': html + row_html(),
        'date': html.replace('2030-01-01 12:00', '2030-99-99 12:00'),
        'foreign_url': html.replace('/entry/fixture', '/manage/posts/'),
        'visibility': html.replace('>공개<', '>새 상태<'),
        'missing_heading': html.replace('티스토리 관리센터 본문', '로그인'),
    }
    rendered = variants.get(case, html)

    def serve(route: Route) -> None:
        route.fulfill(content_type='text/html; charset=utf-8', body=rendered)

    with sync_playwright() as p, closing(p.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        page.route('**/*', serve)
        url = {'origin': 'https://example.test/manage/posts/', 'login': 'https://example.tistory.com/auth/login'}.get(case, 'https://example.tistory.com/manage/posts/')
        page.goto(url)
        identity = PostId('79, input') if case == 'unsafe_id' else PostId('79')
        assert read_manager_post(page, identity) is None


@pytest.mark.parametrize('case', ['reserved', 'plain_title', 'unknown_marker',
                                 'duplicate_marker', 'hidden_marker', 'conflicting_visibility'])
def test_reserved_row_when_visibility_label_is_empty(case: str) -> None:
    # Given: the observed reservation marker, distinct from owner-authored title text.
    marker = '<span class="info_status">[예약]</span>'
    variants = {
        'plain_title': '[예약]',
        'unknown_marker': marker.replace('[예약]', '[다른상태]'),
        'duplicate_marker': marker + marker,
        'hidden_marker': marker.replace('class=', 'hidden class='),
    }
    row = row_html().replace('[예약]', variants.get(case, marker))
    if case != 'conflicting_visibility':
        row = row.replace('>공개<', '><')
    html = '<h2>티스토리 관리센터 본문</h2><ul>' + row + '</ul>'
    requests: list[str] = []

    def serve(route: Route) -> None:
        requests.append(route.request.method)
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as p, closing(p.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        page.route('**/*', serve)
        page.goto('https://example.tistory.com/manage/posts/')
        # When: reading a reservation without inferring visibility or release success.
        result = read_manager_post(page, PostId('79'))
        # Then: only the supported structural reservation is accepted.
        if case == 'reserved':
            assert result is not None
            assert result.reserved is True
            assert result.visibility is None
            assert result.listed_at == datetime.fromisoformat('2030-01-01T12:00:00+09:00')
        else:
            assert result is None
        assert requests == ['GET']
