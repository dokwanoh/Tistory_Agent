from contextlib import closing

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery import playwright_editor_readback as reader
from tistory_growth_os.domain.ids import PostId


@pytest.mark.parametrize('case', ['valid', 'reordered', 'duplicate', 'empty', 'missing',
                                 'wrong_id', 'origin', 'hidden', 'new_editor',
                                 'display_prefix', 'prefix_duplicate', 'prefix_empty'])
def test_tag_readback_when_editor_identity_and_labels_are_observed(case: str) -> None:
    # Given: a synthetic editor, with all requests fulfilled locally.
    variants = {
        'valid': ('테니스', 'US오픈'), 'reordered': ('US오픈', '테니스'),
        'duplicate': ('테니스', '테니스'), 'empty': ('', 'US오픈'), 'missing': (),
        'display_prefix': ('#테니스', '#US오픈'),
        'prefix_duplicate': ('#테니스', '테니스'), 'prefix_empty': ('#', '#US오픈'),
    }
    tags = variants.get(case, variants['valid'])
    hidden = ' hidden' if case == 'hidden' else ''
    html = '<textarea id="post-title-inp">시험 제목</textarea>' + ''.join(
        f'<a href="#" aria-label="{tag} 태그 수정"{hidden}>{tag}</a>' for tag in tags
    )
    requests: list[str] = []

    def serve(route: Route) -> None:
        requests.append(route.request.method)
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as p, closing(p.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        page.route('**/*', serve)
        origin = 'https://example.test' if case == 'origin' else 'https://example.tistory.com'
        path = '/manage/newpost/' if case == 'new_editor' else '/manage/newpost/80'
        page.goto(origin + path)
        identity = PostId('79' if case == 'wrong_id' else '80')
        # When: reading existing tags without clicking or changing the page.
        result = reader.read_editor_tags(page, identity)
        # Then: tag order is immaterial, uncertainty fails closed, no writes occur.
        if case in ('valid', 'reordered', 'display_prefix'):
            assert result is not None
            assert result.post_id == PostId('80')
            assert result.tags == frozenset(('테니스', 'US오픈'))
        else:
            assert result is None
        assert requests == ['GET']
