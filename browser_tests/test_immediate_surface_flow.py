from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Route, sync_playwright
from typing_extensions import override

from tistory_growth_os.delivery.immediate_execution import ImmediateExecutor, ImmediateIntent, ImmediateJournal
from tistory_growth_os.delivery.playwright_article_input import ImmediateArticleInput
from tistory_growth_os.delivery.playwright_immediate_surface import ImmediateNativeSurface
from tistory_growth_os.delivery.playwright_native_surface import NativePreparationError
from tistory_growth_os.delivery.playwright_observation import UploadedAsset
from tistory_growth_os.delivery.reservation_execution import ExecutionState
from tistory_growth_os.delivery.reservation_readback import KST
from browser_tests.test_native_surface_flow import article_fixture, manager_fixture


@pytest.mark.parametrize(('case', 'expected'), [
    ('valid', ExecutionState.VERIFIED),
    ('saved_body', ExecutionState.MISMATCH),
    ('anonymous_body', ExecutionState.MISMATCH),
    ('anonymous_private', ExecutionState.MISMATCH),
    ('platform_media_review', ExecutionState.VERIFIED),
    ('platform_media_wrong_filename', ExecutionState.MISMATCH),
    ('saved_source', ExecutionState.UNKNOWN),
    ('stop_input', ExecutionState.BLOCKED),
    ('repair_body', ExecutionState.VERIFIED),
    ('repair_alt', ExecutionState.VERIFIED),
    ('repair_source', ExecutionState.VERIFIED),
    ('repair_title', ExecutionState.VERIFIED),
    ('repair_missing', ExecutionState.VERIFIED),
    ('resume_editor', ExecutionState.VERIFIED),
    ('repair_preflight', ExecutionState.VERIFIED),
])
def test_immediate_flow_when_real_browser_reads_both_surfaces(case: str, expected: ExecutionState, tmp_path: Path) -> None:
    # Given: native controls and isolated public responses, with every request intercepted.
    original = article_fixture(tmp_path)
    now = datetime.fromisoformat('2030-01-01T15:00:30+09:00')

    class ClockSurface(ImmediateNativeSurface):
        @override
        def now(self) -> datetime:
            return now

    stamp = now.astimezone(KST).strftime('%Y-%m-%d %H:%M')
    intent = ImmediateIntent('fixture-immediate', original.intent.content, 'c' * 64, now + timedelta(hours=1))
    article = ImmediateArticleInput(intent, original.template, original.uploads)
    directory = Path(__file__).parent
    html = (directory / 'native_surface_fixture.html').read_text().replace(
        '{{ARTICLE_INPUT}}', (directory / 'article_input_fixture.html').read_text())
    html = html.replace("setDate(document.querySelectorAll('.btn_date')[1]);",
        f"document.querySelector('.btn_date').textContent = '{stamp}'; setDate(document.querySelector('.btn_date'));")
    if case == 'saved_body':
        html = html.replace('/* SAVED_BODY_VARIANT */', "frame.contentDocument.querySelector('p').textContent='changed';")
    if case == 'saved_source':
        html = html.replace("function saveFixture() {", "function saveFixture() { frame.contentDocument.querySelector('img').src='https://example.com/replaced.jpg';")
    defects = {
        'repair_body': "frame.contentDocument.querySelector('p').textContent = '입력 누락';",
        'repair_alt': "frame.contentDocument.querySelector('img').alt = '';",
        'repair_source': "frame.contentDocument.querySelector('img').src = 'https://cdn.test/wrong.jpg';",
        'repair_title': "document.querySelector('#post-title-inp').value = '잘못된 제목';",
        'repair_missing': "frame.contentDocument.querySelector('img').closest('figure').remove();",
        'resume_editor': "frame.contentDocument.querySelector('img').alt = '';",
    }
    if case in defects:
        html = html.replace('frame.contentDocument.body.innerHTML = result;',
            'frame.contentDocument.body.innerHTML = result; if (!window.correctedOnce) {'
            + defects[case] + 'window.correctedOnce = true;}')
    if case == 'repair_preflight':
        html = html.replace('function openPanel() {', "function openPanel() { if (!window.drifted && location.pathname === '/manage/newpost') {"
            + "frame.contentDocument.querySelector('img').alt=''; window.drifted=true;}")
    saves: list[str] = []
    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        with closing(browser.new_context(service_workers='block')) as authenticated, closing(browser.new_context(service_workers='block')) as anonymous:
            page = authenticated.new_page()
            page.set_default_timeout(3000)

            def serve(route: Route) -> None:
                location = urlsplit(route.request.url)
                if location.netloc != 'example.tistory.com':
                    route.fulfill(status=204)
                    return
                if location.path.rstrip('/') == '/manage/posts':
                    if location.query == 'fixtureSaved=1':
                        saves.append(route.request.url)
                    manager = manager_fixture(('92', '93') if saves else ('92',))
                    manager = manager.replace('<span class="info_status">[예약]</span>', '').replace(
                        '<span class="txt_ellip"></span>', '<span class="txt_ellip">공개</span>').replace('2030-01-01 19:00', stamp)
                    route.fulfill(content_type='text/html; charset=utf-8', body=manager)
                    return
                if location.path == '/93':
                    body = page.frame_locator('#editor-tistory_ifr').locator('#tinymce').inner_html()
                    if case == 'anonymous_body':
                        body = body.replace('검수 본문', 'different text')
                    if case in ('platform_media_review', 'platform_media_wrong_filename'):
                        body = re.sub(r'src="[^"]+"', 'src="https://t1.daumcdn.net/tistory_admin/static/images/pc-image-censoring-v1.gif"', body)
                        if case == 'platform_media_wrong_filename':
                            body = re.sub(r'data-filename="[^"]+"', 'data-filename="wrong.jpg"', body)
                    status = 403 if case == 'anonymous_private' else 200
                    route.fulfill(status=status, content_type='text/html; charset=utf-8',
                                  body='<h1>검수 제목</h1><div class="tt_article_useless_p_margin">' + body + '</div>')
                    return
                route.fulfill(content_type='text/html; charset=utf-8', body=html)

            _ = authenticated.route('**/*', serve)
            _ = anonymous.route('**/*', serve)
            _ = page.goto('https://example.tistory.com/manage/posts/')
            database = tmp_path / 'journal.sqlite3'
            journal = ImmediateJournal(database)

            def checkpoint(phase: str, _uploads: tuple[UploadedAsset, ...]) -> None:
                if case == 'stop_input' and phase == 'article_input/upload_verified' and len(_uploads) == 1:
                    _ = (tmp_path / 'STOP').write_text('stop after first upload')
                if phase == 'article_input/input_verified':
                    journal.media.record(intent.key, intent.package_digest, surface.bindings)
                if case == 'resume_editor' and phase == 'article_input/body_verification':
                    raise NativePreparationError('fixture_interruption_before_save')

            surface = ClockSurface(page, anonymous, article, tmp_path / 'STOP', lambda _request, _now: (), checkpoint)
            surface.recovery_path = tmp_path / 'editor.json'
            if case == 'resume_editor':
                surface.recovery_path = tmp_path / 'editor.json'
                with pytest.raises(NativePreparationError, match='fixture_interruption_before_save'):
                    _ = ImmediateExecutor(journal, surface).run(intent, dry_run=False)
                surface = ClockSurface(page, anonymous, article, tmp_path / 'STOP', lambda _request, _now: ())
                surface.recovery_path = tmp_path / 'editor.json'
                result = ImmediateExecutor(journal, surface).run(intent, dry_run=False, resume_editor=True)
                assert result.execution.state is ExecutionState.VERIFIED
                assert len(saves) == 1
                return
            # When: one independent execution inputs, publishes and reads saved plus anonymous content.
            if case == 'stop_input':
                with pytest.raises(NativePreparationError, match='kill_switch'):
                    _ = ImmediateExecutor(journal, surface).run(intent, dry_run=False)
                assert len(surface.uploads) == 1 and len(saves) == 0
                return
            result = ImmediateExecutor(journal, surface).run(intent, dry_run=False)
            # Then: mismatches never certify, and a second process-equivalent executor never saves again.
            assert result.execution.state is expected, result.execution
            assert len(saves) == 1
            replay = ImmediateExecutor(ImmediateJournal(database), surface).run(intent, dry_run=False)
            assert replay.execution.state is ExecutionState.HELD
            assert len(saves) == 1
            if case == 'valid':
                assert page.url == 'https://example.tistory.com/manage/posts/'
                recovery_surface = ClockSurface(page, anonymous, article, tmp_path / 'STOP', lambda _request, _now: ())
                recovered = ImmediateExecutor(ImmediateJournal(database), recovery_surface).recover(intent)
                assert recovered.execution.state is ExecutionState.UNKNOWN
                assert recovered.execution.reasons == ('missing_readback',)
                recovery_surface.bindings = ImmediateJournal(database).media.read(intent.key, intent.package_digest)
                bound_recovery = ImmediateExecutor(ImmediateJournal(database), recovery_surface).recover(intent)
                assert bound_recovery.execution.state is ExecutionState.VERIFIED
                same_attempt = ImmediateExecutor(ImmediateJournal(database), surface).recover(intent)
                assert same_attempt.execution.state is ExecutionState.VERIFIED
                assert len(saves) == 1
