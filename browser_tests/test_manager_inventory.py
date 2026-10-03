from contextlib import closing
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery import playwright_manager as manager
from tistory_growth_os.domain.ids import PostId


@pytest.mark.parametrize('case', ['complete', 'spa', 'loading', 'duplicate', 'missing_page', 'changed_count', 'filtered'])
def test_inventory_requires_every_unfiltered_page(case: str) -> None:
    # Given: two native-shaped pages, with one optional incompleteness defect.
    requests: list[str] = []

    def serve(route: Route) -> None:
        requests.append(route.request.method)
        number = parse_qs(urlsplit(route.request.url).query).get('page', ['1'])[0]
        identity = '92' if number == '1' or case == 'duplicate' else '91'
        count = '3' if number == '2' and case == 'changed_count' else '2'
        next_link = '' if case == 'missing_page' else (
            '<a class="link_num" href="?category=-3&amp;page=2&amp;visibility=all">2</a>'
        )
        html = f'''<h2>티스토리 관리센터 본문</h2><div id="mArticle">
        <h3>글 관리<span class="txt_count">{count}</span></h3>
        <input type="checkbox" id="inpCheck{identity}">
        <ul class="list_paging"><li><a class="link_num"
        href="?category=-3&amp;page=1&amp;visibility=all">1</a></li>
        <li>{next_link}</li></ul></div>'''
        if case == 'spa':
            html += '''<script>document.querySelectorAll('a')[1].onclick = function(e) {
            e.preventDefault(); history.pushState({}, '', this.href);
            setTimeout(() => document.querySelector('input').id = 'inpCheck91', 300);
            };</script>'''
        if case == 'loading' and number == '1':
            html = html.replace('>2</span>', '>0</span>').replace(
                '<input type="checkbox" id="inpCheck92">', '')
            html += '''<script>setTimeout(() => {
            document.querySelector('.txt_count').textContent = '2';
            document.querySelector('#mArticle').insertAdjacentHTML('beforeend',
            '<input type="checkbox" id="inpCheck92">'); }, 300);</script>'''
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as p, closing(p.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        _ = page.route('**/*', serve)
        query = '?category=123' if case == 'filtered' else ''
        _ = page.goto('https://example.tistory.com/manage/posts/' + query)
        # When: collecting through ordinary visible pagination.
        result = manager.read_manager_inventory(page)
        # Then: partial or conflicting inventories never authorize creation.
        assert result == (frozenset((PostId('91'), PostId('92'))) if case in ('complete', 'spa', 'loading') else None)
        assert set(requests) == {'GET'}
