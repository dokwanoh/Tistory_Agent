from datetime import datetime, tzinfo
import fcntl
import json
from pathlib import Path
import sys
from typing import Literal
from urllib.parse import urlsplit

from playwright.sync_api import Browser, BrowserContext, BrowserType, Route
import pytest
from typing_extensions import override

from browser_tests.test_native_surface_flow import manager_fixture
from tests.test_immediate_package import immediate_package_fixture
from tistory_growth_os.delivery import immediate_runner
from tistory_growth_os.delivery.immediate_package import load_immediate_package
from tistory_growth_os.delivery.playwright_immediate_surface import ImmediateNativeSurface


def test_cli_when_independent_immediate_attempt_and_recovery_use_real_chrome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: exact reviewed files, scoped authority and intercepted native surfaces.
    fixed = datetime.fromisoformat('2030-01-01T15:00:30+09:00')

    class Clock(datetime):
        @classmethod
        @override
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return fixed.astimezone(tz) if tz is not None else fixed.replace(tzinfo=None)

    def surface_clock(_surface: ImmediateNativeSurface) -> datetime:
        return fixed

    folder = immediate_package_fixture(tmp_path)
    manifest = folder / 'manifest.json'
    _ = manifest.write_text(manifest.read_text().replace('"home_topic":"생활정보"', '"home_topic":"국내여행"')
        .replace('"tags":["해안"]', '"tags":["AI","LG이노텍","해안"]'))
    package = load_immediate_package(tmp_path, folder, fixed)
    digest = package.article.intent.package_digest
    review_directory = tmp_path / 'contracts' / 'reviews'
    review_directory.mkdir(parents=True)
    _ = (review_directory / (digest + '.json')).write_text(json.dumps({
        'schema_version': '1.0.0', 'scope': 'local_package_only', 'review_id': 'review_fixture',
        'reviewer_id': 'fixture_agent', 'reviewer_kind': 'independent_agent', 'decision': 'approved',
        'subject_sha256': digest, 'reviewed_at': '2030-01-01T14:30:00+09:00',
        'valid_until': '2030-01-01T20:00:00+09:00', 'evidence_valid_until': '2030-01-02T01:00:00+09:00',
        'policy_valid_until': '2030-01-02T00:00:00+09:00'}))
    _ = (tmp_path / 'authority.json').write_text(json.dumps({
        'scope': 'one-article-native-immediate', 'approval_id': 'fixture-owner', 'operation_id': 'manual-one',
        'approved_at': '2030-01-01T14:30:00+09:00', 'package_digest': digest,
        'valid_until': '2030-01-01T18:00:00+09:00'}))
    directory = Path(__file__).parent
    html = (directory / 'native_surface_fixture.html').read_text().replace(
        '{{ARTICLE_INPUT}}', (directory / 'article_input_fixture.html').read_text())
    html = html.replace('sessionStorage', 'localStorage').replace(
        "setDate(document.querySelectorAll('.btn_date')[1]);",
        "document.querySelector('.btn_date').textContent='2030-01-01 15:00';setDate(document.querySelector('.btn_date'));")
    html = html.replace('map(link => link.textContent),',
        "map(link => link.textContent.replace(/[A-Z]/g, letter => letter.toLowerCase())),")
    saves: list[str] = []
    authenticated: list[BrowserContext] = []
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
            manager = manager_fixture(('92', '93') if saves else ('92',)).replace(
                '<span class="info_status">[예약]</span>', '').replace(
                '<span class="txt_ellip"></span>', '<span class="txt_ellip">공개</span>').replace(
                '2030-01-01 19:00', '2030-01-01 15:00')
            route.fulfill(content_type='text/html; charset=utf-8', body=manager)
            return
        if location.path == '/93':
            body = authenticated[-1].pages[0].frame_locator('#editor-tistory_ifr').locator('#tinymce').inner_html()
            route.fulfill(content_type='text/html; charset=utf-8', body=
                '<h1>검수 제목</h1><div class="tt_article_useless_p_margin">' + body + '</div>')
            return
        route.fulfill(content_type='text/html; charset=utf-8', body=html)

    original_launch = BrowserType.launch_persistent_context
    original_context = Browser.new_context

    def launch(self: BrowserType, user_data_dir: str, *, channel: str, headless: bool,
               chromium_sandbox: bool, accept_downloads: bool,
               service_workers: Literal['allow', 'block']) -> BrowserContext:
        assert not headless
        context = original_launch(self, user_data_dir, channel=channel, headless=True,
            chromium_sandbox=chromium_sandbox, accept_downloads=accept_downloads, service_workers=service_workers)
        _ = context.route('**/*', serve)
        authenticated.append(context)
        return context

    def new_context(self: Browser, *, accept_downloads: bool,
                    service_workers: Literal['allow', 'block']) -> BrowserContext:
        context = original_context(self, accept_downloads=accept_downloads, service_workers=service_workers)
        _ = context.route('**/*', serve)
        return context

    monkeypatch.chdir(tmp_path)
    profile = tmp_path / 'browser-profile'
    profile.mkdir()
    (profile / 'Local State').write_text(json.dumps({'profile': {'info_cache': {'Default': {'name': '내 Chrome'}}}}))
    (profile / 'tistory-profile.json').write_text(json.dumps({
        'logical_name': 'Tistory Publisher', 'blog_host': 'example.tistory.com', 'profile_directory': 'Default'}))
    monkeypatch.setattr(immediate_runner, 'datetime', Clock)
    monkeypatch.setattr(ImmediateNativeSurface, 'now', surface_clock)
    monkeypatch.setattr(BrowserType, 'launch_persistent_context', launch)
    monkeypatch.setattr(Browser, 'new_context', new_context)
    arguments = ['immediate_runner', '--package', 'content/pilot', '--execute', '--authority', 'authority.json']
    monkeypatch.setattr(sys, 'argv', arguments)
    runtime_directory = tmp_path / '.artifacts' / 'native-runtime'
    runtime_directory.mkdir(parents=True)
    with (runtime_directory / 'worker.lock').open('a') as competing_worker:
        fcntl.flock(competing_worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held = immediate_runner.main()
        held_output = capsys.readouterr().out
        assert held == 2 and 'BlockingIOError' in held_output
        assert not authenticated and not saves
    # When: the real CLI entrypoint executes once, then receives replay and read-only recovery.
    result = immediate_runner.main()
    first_output = capsys.readouterr().out
    replay = immediate_runner.main()
    replay_output = capsys.readouterr().out
    monkeypatch.setattr(sys, 'argv', [*arguments, '--recover'])
    recovered = immediate_runner.main()
    recovered_output = capsys.readouterr().out
    # Then: only one save occurred; hashes survive process-equivalent browser restarts.
    assert result == 0 and '"state": "verified"' in first_output, first_output
    assert replay == 2 and 'existing_intent' in replay_output, replay_output
    assert recovered == 0 and '"state": "verified"' in recovered_output, recovered_output
    assert len(saves) == 1
    assert set(requests) == {'GET'}
