from contextlib import closing
from hashlib import sha256

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery import playwright_html_input as writer


@pytest.mark.parametrize('case', ['valid', 'dry_run', 'existing_post', 'existing_title',
                                 'existing_body', 'wrong_origin', 'wrong_digest', 'missing'])
def test_html_input_when_only_an_empty_new_editor_is_targeted(case: str) -> None:
    title = '시험 입력'
    body = '<h2>제목</h2><p>짧은 문단입니다.</p>'
    digest = sha256(body.encode()).hexdigest()
    html = '<textarea id="post-title-inp"></textarea><div id="html-editor-container"><div class="CodeMirror"><textarea></textarea></div></div>'
    variants = {
        'existing_title': html.replace('id="post-title-inp">', 'id="post-title-inp">기존 제목'),
        'existing_body': html.replace('<textarea></textarea>', '<textarea>기존 본문</textarea>'),
        'missing': html.replace('html-editor-container', 'other'),
    }
    requests: list[str] = []

    def serve(route: Route) -> None:
        requests.append(route.request.method)
        route.fulfill(content_type='text/html; charset=utf-8', body=variants.get(case, html))

    with sync_playwright() as p, closing(p.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        page.route('**/*', serve)
        origin = 'https://example.test' if case == 'wrong_origin' else 'https://example.tistory.com'
        suffix = '80' if case == 'existing_post' else ''
        page.goto(origin + '/manage/newpost/' + suffix)
        before = page.locator('textarea').all_text_contents()
        request = writer.HtmlInput(title, body, '0' * 64 if case == 'wrong_digest' else digest)
        result = writer.fill_blank_html_editor(page, request, dry_run=case == 'dry_run')
        if case == 'valid':
            assert result is writer.InputResult.INPUT_VERIFIED
            assert page.locator('#post-title-inp').input_value() == title
            assert page.locator('.CodeMirror textarea').input_value() == body
        else:
            assert result is (writer.InputResult.DRY_RUN if case == 'dry_run' else writer.InputResult.BLOCKED)
            assert [item.input_value() for item in page.locator('textarea').all()] == before
        assert requests == ['GET']
