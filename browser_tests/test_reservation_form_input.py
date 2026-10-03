from contextlib import closing
from datetime import datetime

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery import playwright_publish_settings as settings
from tistory_growth_os.delivery.new_reservation_identity import NewReservationIntent
from tistory_growth_os.delivery.reservation_readback import ReservationContent, ReservationMedia
from tistory_growth_os.domain.ids import MediaId


def request_fixture() -> NewReservationIntent:
    media = tuple(ReservationMedia(MediaId(str(n)), f'그림 {n}') for n in range(4))
    content = ReservationContent('시험 글', 'a' * 64, media, MediaId('0'),
                                 '생활정보', '국내여행', ('철도',))
    return NewReservationIntent(datetime.fromisoformat('2030-01-01T19:00:00+09:00'), content, 'b' * 64)


@pytest.mark.parametrize('case', ['valid', 'dry_run', 'existing_post', 'wrong_title', 'wrong_day'])
def test_native_reservation_form_when_same_new_article_is_bound(case: str) -> None:
    # Given: normal editor controls; the final button is instrumented but must never fire.
    html = '''<textarea id="post-title-inp">시험 글</textarea>
    <button id="category-btn" onclick="document.querySelector('#category-list').hidden=false">카테고리 없음</button>
    <div id="category-list" hidden><span class="mce-text" onclick="document.querySelector('#category-btn').textContent=this.textContent;this.parentElement.hidden=true">생활정보</span></div>
    <input id="tagText" onkeydown="if(event.key==='Enter'){let a=document.createElement('a');a.href='#';a.setAttribute('aria-label',this.value+' 태그 수정');a.textContent=this.value;this.after(a);this.value=''}">
    <button id="publish-layer-btn" onclick="document.querySelector('[role=dialog]').hidden=false">완료</button>
    <div role="dialog" hidden><legend>발행정보 입력폼</legend><strong class="tit_publish">시험 글</strong>
    <input id="open20" name="basicSet" value="20" type="radio"><label for="open20">공개</label>
    <dl id="home_subject"><button onclick="document.querySelector('[role=menuitem]').hidden=false"><span class="mce-txt">선택 안 함</span></button></dl>
    <button class="btn_date on" onclick="document.querySelectorAll('.btn_date').forEach(x=>x.classList.remove('on'));this.classList.add('on')">현재</button>
    <button class="btn_date" onclick="document.querySelectorAll('.btn_date').forEach(x=>x.classList.remove('on'));this.classList.add('on');document.querySelector('#reservation').hidden=false">예약</button>
    <div id="reservation" hidden><button class="btn_reserve">2030-01-01</button><input type="number" id="dateHour" value="14"><input type="number" id="dateMinute" value="27"></div>
    <button id="final" onclick="this.textContent='WRITTEN'">공개 발행</button></div>
    <div role="menuitem" hidden onclick="document.querySelector('#home_subject .mce-txt').textContent='국내여행';this.hidden=true">- 국내여행</div>'''
    variants = {'wrong_title': html.replace('시험 글', '다른 글'),
                'wrong_day': html.replace('2030-01-01', '2030-01-02')}

    def serve(route: Route) -> None:
        route.fulfill(content_type='text/html; charset=utf-8', body=variants.get(case, html))

    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        _ = page.route('**/*', serve)
        _ = page.goto('https://example.tistory.com/manage/newpost' + ('/92' if case == 'existing_post' else ''))
        # When: configuring only, with no final save authority in this primitive.
        result = settings.configure_new_reservation(page, request_fixture(), dry_run=case == 'dry_run')
        # Then: only the matching same-day new editor reaches verified form state.
        assert result == ('dry_run' if case == 'dry_run' else 'input_verified' if case == 'valid' else 'blocked')
        assert page.locator('#final').inner_text() == '공개 발행'
        if case == 'valid':
            assert page.locator('#dateHour').input_value() == '19'
            assert page.locator('#dateMinute').input_value() == '00'
            assert page.locator('#open20').is_checked()
            assert page.locator('#home_subject .mce-txt').inner_text() == '국내여행'
            assert page.locator('#category-btn').inner_text() == '생활정보'
            assert page.get_by_role('link', name='철도 태그 수정').count() == 1
