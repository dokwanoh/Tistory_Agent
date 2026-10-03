from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Route, sync_playwright

from browser_tests.test_native_surface_flow import article_fixture, manager_fixture
from tistory_growth_os.delivery.new_reservation_execution import NewReservationExecutor
from tistory_growth_os.delivery.playwright_native_surface import NativeSurface
from tistory_growth_os.delivery.reservation_execution import ExecutionState
from tistory_growth_os.delivery.save_intents import SaveIntentJournal


@pytest.mark.parametrize('tamper', [False, True])
def test_retained_editor_resume_after_executor_restart(tmp_path: Path, tamper: bool) -> None:
    # Given: a prepared editor, durable SQLite, and fully intercepted Chrome traffic.
    article = article_fixture(tmp_path)
    directory = Path(__file__).parent
    html = (directory / 'native_surface_fixture.html').read_text().replace(
        '{{ARTICLE_INPUT}}', (directory / 'article_input_fixture.html').read_text())
    saves: list[str] = []

    def serve(route: Route) -> None:
        location = urlsplit(route.request.url)
        if location.netloc != 'example.tistory.com':
            route.fulfill(status=204)
        elif location.path.rstrip('/') == '/manage/posts':
            if location.query == 'fixtureSaved=1':
                saves.append('save')
            route.fulfill(content_type='text/html; charset=utf-8', body=manager_fixture(('92', '93') if saves else ('92',)))
        else:
            route.fulfill(content_type='text/html; charset=utf-8', body=html)

    path = tmp_path / 'journal.db'
    with sync_playwright() as runtime, closing(runtime.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        context = browser.new_context(service_workers='block')
        _ = context.route('**/*', serve)
        page = context.new_page()
        _ = page.goto('https://example.tistory.com/manage/posts/')
        first = NativeSurface(page, article, lambda: first.phase == 'final_preflight', lambda _r, _n: ())
        result = NewReservationExecutor(SaveIntentJournal(path), first).run(article.intent, dry_run=False)
        assert result.execution.state is ExecutionState.BLOCKED and not saves
        if tamper:
            page.locator('#post-title-inp').fill('변경된 제목')
        fresh = NativeSurface(page, article, lambda: False, lambda _r, _n: (), preserve_editor=True)
        # When: a new executor resumes using the retained editor, not a replacement.
        resumed = NewReservationExecutor(SaveIntentJournal(path), fresh).resume(article.intent, dry_run=False)
        # Then: exact state saves once; altered content never saves.
        assert resumed.execution.state is (ExecutionState.HELD if tamper else ExecutionState.VERIFIED)
        assert len(saves) == (0 if tamper else 1)
