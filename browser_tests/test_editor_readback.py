from contextlib import closing
from hashlib import sha256
from html import escape

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery.playwright_editor_readback import read_editor_content
from tistory_growth_os.domain.ids import PostId


def body_html() -> str:
    return '<p>시험 본문</p>' + ''.join(
        f'<figure data-ke-type="image"><img src="https://example.test/{i}.png" '
        f'alt="설명 {i}" data-filename="image-{i}.png"></figure>' for i in range(4)
    )


def editor_html(body: str) -> str:
    frame = '<body id="tinymce" contenteditable="true">' + body + '</body>'
    return ('<textarea id="post-title-inp">시험 제목</textarea>'
            f'<iframe id="editor-tistory_ifr" srcdoc="{escape(frame, quote=True)}"></iframe>')


def test_editor_content_preserves_native_bytes_and_order_without_writes() -> None:
    # Given: a native-shaped editor served entirely from a fixture.
    requests: list[str] = []

    def serve(route: Route) -> None:
        requests.append(route.request.method)
        route.fulfill(content_type='text/html; charset=utf-8', body=editor_html(body_html()))

    with sync_playwright() as p, closing(p.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        page.route('**/*', serve)
        page.goto('https://example.tistory.com/manage/newpost/79')
        page.frame_locator('#editor-tistory_ifr').locator('#tinymce').wait_for()
        # When: reading the currently loaded representation.
        result = read_editor_content(page, PostId('79'))
        # Then: exact observed bytes and media order, without navigation/save.
        assert result is not None
        assert result.post_id == PostId('79')
        assert result.title == '시험 제목'
        assert result.body_html == body_html()
        assert result.body_sha256 == sha256(body_html().encode()).hexdigest()
        assert [item.alt for item in result.media] == [f'설명 {i}' for i in range(4)]
        assert [item.source_url for item in result.media] == [f'https://example.test/{i}.png' for i in range(4)]
        assert [item.filename for item in result.media] == [f'image-{i}.png' for i in range(4)]
        assert set(requests) == {'GET'}


@pytest.mark.parametrize('case', ['origin', 'wrong_id', 'unsafe_id', 'missing_frame',
                                 'duplicate_title', 'empty_title', 'missing_alt',
                                 'blob_image', 'duplicate_image', 'three_images'])
def test_unsupported_editor_returns_no_snapshot(case: str) -> None:
    # Given: an ambiguous identity, unsupported surface or incomplete media.
    body = body_html()
    variants = {
        'missing_alt': body.replace('alt="설명 0"', ''),
        'blob_image': body.replace('https://example.test/0.png', 'blob:pending'),
        'duplicate_image': body.replace('https://example.test/1.png', 'https://example.test/0.png'),
        'three_images': body[:body.rfind('<figure')],
    }
    html = editor_html(variants.get(case, body))
    pages = {
        'missing_frame': html.replace('editor-tistory_ifr', 'unknown-frame'),
        'duplicate_title': html + '<textarea id="post-title-inp">other</textarea>',
        'empty_title': html.replace('시험 제목', ''),
    }

    def serve(route: Route) -> None:
        route.fulfill(content_type='text/html; charset=utf-8', body=pages.get(case, html))

    with sync_playwright() as p, closing(p.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        page.route('**/*', serve)
        origin = 'https://example.test' if case == 'origin' else 'https://example.tistory.com'
        page.goto(origin + '/manage/newpost/79')
        page.frame_locator('iframe').locator('#tinymce').wait_for()
        identity = {'wrong_id': '80', 'unsafe_id': '79/../80'}.get(case, '79')
        # When / Then: uncertainty cannot become verification evidence.
        assert read_editor_content(page, PostId(identity)) is None
