from contextlib import closing
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery.editor_body_fingerprint import article_body_digest
from tistory_growth_os.delivery.native_article_source import NativeAlt
from tistory_growth_os.delivery.new_reservation_identity import NewReservationIntent
from tistory_growth_os.delivery.playwright_article_input import ArticleInput, input_new_article
from tistory_growth_os.delivery.playwright_html_input import LocalUpload
from tistory_growth_os.delivery.playwright_observation import UploadedAsset
from tistory_growth_os.delivery.reservation_readback import ReservationContent, ReservationMedia
from tistory_growth_os.domain.ids import MediaId


@pytest.mark.parametrize('case', ['valid', 'dry_run', 'dirty_body', 'wrong_file', 'transform'])
def test_article_assembly_uses_native_controls_and_rejects_changed_body(case: str, tmp_path: Path) -> None:
    uploads: list[LocalUpload] = []
    for index in range(4):
        path = tmp_path / f'{index}.jpg'
        _ = path.write_bytes(f'fixture {index}'.encode())
        uploads.append(LocalUpload(MediaId(str(index)), path, sha256(path.read_bytes()).hexdigest(), '검수 제목'))
    media = tuple(ReservationMedia(MediaId(str(index)), f'사진 {index}') for index in range(4))
    alts = tuple(NativeAlt(f'{index}.jpg', image.alt) for index, image in enumerate(media))
    template = '<p>검수 본문</p>' + ''.join(f'{{{{MEDIA{index}}}}}' for index in range(1, 5))
    digest = article_body_digest(template, alts)
    assert digest is not None
    intent = NewReservationIntent(datetime.fromisoformat('2030-01-01T19:00:00+09:00'),
                                  ReservationContent('검수 제목', digest, media, MediaId('0'), '생활정보', '생활정보', ('해안',)), 'a' * 64)
    if case == 'wrong_file':
        uploads[0] = replace(uploads[0], sha256_digest='0' * 64)
    request = ArticleInput(intent, template, tuple(uploads))
    assert request.valid() is (case != 'wrong_file')
    html = Path(__file__).with_name('article_input_fixture.html').read_text()
    if case == 'dirty_body':
        html = html.replace('contenteditable="true"></body>', 'contenteditable="true">기존 원고</body>')

    def serve(route: Route) -> None:
        if 'cdn.test' in route.request.url:
            route.fulfill(status=204)
        else:
            route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        _ = page.route('**/*', serve)
        _ = page.goto('https://example.tistory.com/manage/newpost' + ('?transform' if case == 'transform' else ''))
        page.frame_locator('iframe').locator('body').wait_for()
        progress: list[tuple[str, tuple[UploadedAsset, ...]]] = []

        def checkpoint(stage: str, receipts: tuple[UploadedAsset, ...]) -> None:
            progress.append((stage, receipts))

        result = input_new_article(page, request, dry_run=case == 'dry_run', checkpoint=checkpoint)
        assert (result is not None) is (case == 'valid'), (page.locator('#post-title-inp').input_value(), page.frame_locator('iframe').locator('body').inner_html())
        images = page.frame_locator('iframe').locator('img')
        assert images.count() == (4 if case in ('valid', 'transform') else 0)
        if case in ('valid', 'transform'):
            assert [len(receipts) for stage, receipts in progress if stage == 'upload_verified'] == [1, 2, 3, 4]
            assert progress[-1][0] == ('input_verified' if case == 'valid' else 'body_verification')
        else:
            assert not progress
        if result is not None:
            assert tuple(item.asset_id for item in result) == tuple(item.asset_id for item in media)
            assert tuple(image.get_attribute('alt') for image in images.all()) == tuple(item.alt for item in media)
