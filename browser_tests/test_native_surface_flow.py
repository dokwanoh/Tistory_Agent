from contextlib import closing
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery.editor_body_fingerprint import article_body_digest
from tistory_growth_os.delivery.native_article_source import NativeAlt
from tistory_growth_os.delivery.new_reservation_execution import NewReservationExecutor
from tistory_growth_os.delivery.new_reservation_identity import NewReservationIntent
from tistory_growth_os.delivery.playwright_article_input import ArticleInput
from tistory_growth_os.delivery.playwright_html_input import LocalUpload
from tistory_growth_os.delivery.playwright_native_surface import NativeSurface
from tistory_growth_os.delivery.reservation_execution import ExecutionState
from tistory_growth_os.delivery.reservation_readback import DailySlot, ReservationContent, ReservationMedia
from tistory_growth_os.delivery.save_intents import SaveIntentJournal
from tistory_growth_os.domain.ids import MediaId, PostId


def article_fixture(directory: Path) -> ArticleInput:
    uploads: list[LocalUpload] = []
    media = tuple(ReservationMedia(MediaId(str(index)), f'사진 {index}') for index in range(4))
    for index in range(4):
        path = directory / f'{index}.jpg'
        payload = f'synthetic media {index}'.encode()
        _ = path.write_bytes(payload)
        uploads.append(LocalUpload(MediaId(str(index)), path, sha256(payload).hexdigest(), '검수 제목'))
    template = '<p>검수 본문</p>' + ''.join(f'{{{{MEDIA{index}}}}}' for index in range(1, 5))
    alts = tuple(NativeAlt(f'{index}.jpg', item.alt) for index, item in enumerate(media))
    digest = article_body_digest(template, alts)
    assert digest is not None
    content = ReservationContent('검수 제목', digest, media, MediaId('0'), '생활정보', '국내여행', ('해안',))
    intent = NewReservationIntent(datetime.fromisoformat('2030-01-01T19:00:00+09:00'), content, 'a' * 64)
    return ArticleInput(intent, template, tuple(uploads))


def manager_fixture(identities: tuple[str, ...]) -> str:
    rows = ''.join(f'''<li><input type="checkbox" id="inpCheck{identity}">
    <a class="link_cont" href="https://example.tistory.com/{identity}"><span class="info_status">[예약]</span>검수 제목</a>
    <span class="txt_cate">생활정보</span><span class="txt_info">2030-01-01 19:00</span>
    <button class="btn_opt"><span class="txt_ellip"></span></button></li>''' for identity in identities)
    return f'''<h2>티스토리 관리센터 본문</h2><div id="mArticle">
    <h3>글 관리<span class="txt_count">{len(identities)}</span></h3><ul>{rows}</ul></div>'''


@pytest.mark.parametrize(('case', 'expected'), [
    ('valid', ExecutionState.VERIFIED),
    ('zero_height_label', ExecutionState.VERIFIED),
    ('modal_hidden_tags', ExecutionState.VERIFIED),
    ('body_mismatch', ExecutionState.MISMATCH),
    ('extra_identity', ExecutionState.UNKNOWN),
])
def test_native_flow_when_saved_surfaces_are_reconciled(case: str, expected: ExecutionState, tmp_path: Path) -> None:
    # Given: a complete synthetic editor and manager; all browser traffic is intercepted.
    article = article_fixture(tmp_path)
    directory = Path(__file__).parent
    html = (directory / 'native_surface_fixture.html').read_text().replace(
        '{{ARTICLE_INPUT}}', (directory / 'article_input_fixture.html').read_text())
    if case == 'zero_height_label':
        html = html.replace('<label for="open20">', '<label for="open20" style="display:block;height:0;overflow:hidden">')
    if case == 'modal_hidden_tags':
        html = html.replace('const cover =', "document.querySelectorAll('a[aria-label]').forEach(link => link.setAttribute('aria-hidden','true')); const cover =")
    if case == 'body_mismatch':
        html = html.replace('/* SAVED_BODY_VARIANT */',
                            "frame.contentDocument.querySelector('p').textContent = '변조 본문';")
    saves: list[str] = []
    requests: list[str] = []

    def serve(route: Route) -> None:
        location = urlsplit(route.request.url)
        requests.append(route.request.method)
        if location.netloc != 'example.tistory.com':
            route.fulfill(status=204)
            return
        if location.path.rstrip('/') == '/manage/posts':
            if location.query == 'fixtureSaved=1':
                saves.append(route.request.url)
            identities = ('92', '93', '94') if saves and case == 'extra_identity' else ('92', '93') if saves else ('92',)
            route.fulfill(content_type='text/html; charset=utf-8', body=manager_fixture(identities))
            return
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    database = tmp_path / 'save-intents.sqlite3'
    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        page.set_default_timeout(3000)
        _ = page.route('**/*', serve)
        _ = page.goto('https://example.tistory.com/manage/posts/')
        surface = NativeSurface(page, article, lambda: False, lambda _request, _now: ())
        executor = NewReservationExecutor(SaveIntentJournal(database), surface)
        # When: the real adapter inputs, saves once, discovers identity and reads saved content.
        result = executor.run(article.intent, dry_run=False)
        # Then: agreement verifies; changed content or ambiguous identity cannot verify.
        assert result.execution.state is expected, result.execution
        assert len(saves) == 1
        assert surface.save_attempted
        receipt = SaveIntentJournal(database).receipt(DailySlot(article.intent.scheduled_at).key, article.intent.package_digest)
        if case == 'extra_identity':
            assert receipt is None and result.target is None
        else:
            assert receipt is not None and receipt.post_id == PostId('93')
            assert result.target is not None and result.target.post_id == PostId('93')
        if case == 'body_mismatch':
            assert 'body_digest' in result.execution.reasons
        if case == 'valid':
            recovery = NewReservationExecutor(SaveIntentJournal(database), surface).recover(article.intent)
            assert recovery.execution.state is ExecutionState.VERIFIED
            assert recovery.target == result.target
            assert len(saves) == 1
        fresh_surface = NativeSurface(page, article, lambda: False, lambda _request, _now: ())
        replay = NewReservationExecutor(SaveIntentJournal(database), fresh_surface).run(article.intent, dry_run=False)
        assert replay.execution.state is ExecutionState.HELD
        assert replay.execution.reasons == ('existing_intent',)
        assert not fresh_surface.prepared and not fresh_surface.save_attempted
        assert len(saves) == 1
        assert set(requests) == {'GET'}


def test_native_flow_when_runtime_authority_is_missing(tmp_path: Path) -> None:
    # Given: a valid local article and browser surface without an authority callback.
    article = article_fixture(tmp_path)
    journal = SaveIntentJournal(tmp_path / 'save-intents.sqlite3')
    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        _ = page.route('**/*', lambda route: route.abort())
        surface = NativeSurface(page, article, lambda: False)
        # When: requesting real execution without runtime authority.
        result = NewReservationExecutor(journal, surface).run(article.intent, dry_run=False)
        # Then: the gate blocks before inventory, article input, journal claim or save.
        assert result.execution.state is ExecutionState.BLOCKED
        assert result.execution.reasons == ('runtime_authority_required',)
        assert surface.prior is None and not surface.prepared and not surface.save_attempted
        assert page.url == 'about:blank'
        assert journal.claim(DailySlot(article.intent.scheduled_at).key, article.intent.package_digest)
