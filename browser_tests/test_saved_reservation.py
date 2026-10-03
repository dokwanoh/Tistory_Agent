from contextlib import closing
from datetime import datetime
from dataclasses import replace

import pytest
from playwright.sync_api import Route, sync_playwright

from browser_tests.test_editor_readback import body_html, editor_html
from browser_tests.test_publish_settings import panel_html
from tistory_growth_os.delivery import playwright_saved_reservation as reader
from tistory_growth_os.delivery.playwright_manager import ManagerPostSummary
from tistory_growth_os.delivery.playwright_editor_readback import read_editor_tags
from tistory_growth_os.domain.ids import PostId
from tistory_growth_os.domain.ids import MediaId
from tistory_growth_os.delivery.playwright_observation import UploadedAsset, reservation_observation


@pytest.mark.parametrize('case', ['valid', 'wrong_id', 'wrong_time', 'wrong_title',
                                 'wrong_slug', 'not_reserved', 'missing_thumb',
                                 'foreign_thumb', 'unknown_image', 'duplicate_fname', 'missing_tags'])
def test_integrated_readback_when_saved_surfaces_agree(case: str) -> None:
    # Given: independent manager metadata and a native-shaped editor with publish panel.
    scheduled = datetime.fromisoformat('2030-01-01T19:00:00+09:00')
    manager = ManagerPostSummary(PostId('80' if case == 'wrong_id' else '79'),
                                '[예약]시험 제목', 'https://example.tistory.com/entry/fixture-post',
                                '스포츠', scheduled, None, case != 'not_reserved')
    thumb = '<span class="thumb_g" style="background-image: url(&quot;https://img1.daumcdn.net/thumb/C170x170/?scode=fixture&amp;fname=https%3A%2F%2Fexample.test%2F0.png&quot;);"><button>삭제</button></span>'
    controls = '<button class="btn_reserve">2030-01-01</button><input id="dateHour" type="number" value="19"><input id="dateMinute" type="number" value="00">'
    panel = panel_html().replace('2030-01-01 12:00', '예약').replace('</div>', controls + thumb + '</div>')
    tags = '<a href="#" aria-label="테니스 태그 수정">#테니스</a>'
    html = editor_html(body_html()) + tags + panel
    variants = {
        'wrong_time': html.replace('value="19"', 'value="18"'),
        'wrong_title': html.replace('class="tit_publish">시험 제목', 'class="tit_publish">다른 제목'),
        'wrong_slug': html.replace('value="fixture-post"', 'value="another"'),
        'missing_thumb': html.replace(thumb, ''),
        'foreign_thumb': html.replace('img1.daumcdn.net', 'example.test'),
        'unknown_image': html.replace('%2F0.png', '%2F9.png'),
        'duplicate_fname': html.replace('scode=fixture', 'fname=other&amp;scode=fixture'),
        'missing_tags': html.replace(tags, ''),
    }
    requests: list[str] = []

    def serve(route: Route) -> None:
        requests.append(route.request.method)
        route.fulfill(content_type='text/html; charset=utf-8', body=variants.get(case, html))

    with sync_playwright() as p, closing(p.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        _ = page.route('**/*', serve)
        _ = page.goto('https://example.tistory.com/manage/newpost/79')
        page.frame_locator('#editor-tistory_ifr').locator('#tinymce').wait_for()
        # When: composing observations without editing or saving.
        result = reader.read_saved_reservation(page, manager, read_editor_tags(page, PostId('79')))
        # Then: disagreement blocks a combined snapshot.
        if case == 'valid':
            assert result is not None
            assert result.representative_index == 0
            assert result.content.title == '시험 제목'
            assert len(result.content.media) == 4
            assert result.tags.tags == frozenset(('테니스',))
            assert result.settings.scheduled_at == scheduled
            bindings = tuple(UploadedAsset(MediaId(f'asset-{i}'), f'https://example.test/{i}.png',
                                           f'image-{i}.png') for i in range(4))
            observed = reservation_observation(result, bindings, scheduled)
            assert observed is not None
            assert observed.target.post_id == '79'
            assert observed.target.content.body_digest == result.content.body_sha256
            assert observed.target.content.representative == 'asset-0'
            assert observed.target.content.media[2].alt == '설명 2'
            assert observed.target.content.category == '스포츠'
            assert reservation_observation(result, bindings[:3], scheduled) is None
            wrong = (replace(bindings[0], filename='different.png'), *bindings[1:])
            assert reservation_observation(result, wrong, scheduled) is None
            swapped = replace(result, content=replace(result.content, media=tuple(reversed(result.content.media))))
            changed = reservation_observation(swapped, bindings, scheduled)
            assert changed is not None and changed.target.content.media[0].asset_id == 'asset-3'
        else:
            assert result is None
        assert set(requests) == {'GET'}
