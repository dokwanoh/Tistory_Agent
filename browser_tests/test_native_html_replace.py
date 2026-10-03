from contextlib import closing
from hashlib import sha256

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery import playwright_html_input as writer


@pytest.mark.parametrize('case', ['valid', 'dry_run', 'changed_source', 'wrong_title', 'existing_post'])
def test_native_html_replacement_is_bound_to_exact_prior_bytes(case: str) -> None:
    # Given: native source already contains the uploads for the same new article.
    before = '[##_Image|fixture-upload_##]'
    after = '<p>새 본문</p>' + before
    html = '<textarea id="post-title-inp">시험 글</textarea><div id="html-editor-container"><div class="CodeMirror"><textarea>' + before + '</textarea></div></div>'

    def serve(route: Route) -> None:
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        _ = page.route('**/*', serve)
        _ = page.goto('https://example.tistory.com/manage/newpost' + ('/92' if case == 'existing_post' else ''))
        source = page.locator('.CodeMirror textarea')
        request = writer.HtmlReplacement(
            writer.HtmlInput('다른 글' if case == 'wrong_title' else '시험 글', after, sha256(after.encode()).hexdigest()),
            '0' * 64 if case == 'changed_source' else sha256(before.encode()).hexdigest())
        # When: real keyboard input replaces only the exactly bound source.
        result = writer.replace_uploaded_html(page, request, dry_run=case == 'dry_run')
        # Then: changed or unrelated content remains untouched, and no save is attempted.
        assert result == ('dry_run' if case == 'dry_run' else 'input_verified' if case == 'valid' else 'blocked')
        assert source.input_value() == (after if case == 'valid' else before)
