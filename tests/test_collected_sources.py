from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256
import json

import pytest

from tistory_growth_os.preparation import source_capture as cli
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation import runner, source_pool
from tistory_growth_os.preparation.contracts import parse_research
from tests.preparation_fixture import NOW as FIXTURE_NOW, research_response
from tests.preparation_fixture import FixtureProvider
from tests.test_preparation_flow import prepared_run
from tistory_growth_os.preparation.provider import StageRequest, StageResponse


NOW = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)
URL = 'https://mediahub.seoul.go.kr/archives/12345'
BODY = '새로운 상담 서비스는 다음 달부터 운영됩니다. 이용 방법과 운영 범위를 안내합니다. ' * 20
FEED = ('<rss><channel><item><title>새 상담 안내</title><link>' + URL
        + '</link><pubDate>Wed, 23 Sep 2026 16:00:00 +0900</pubDate>'
        + '</item></channel></rss>').encode()
HTML = ('<html><h1>새 상담 안내</h1><p>발행일 2026.09.23. 16:00</p>'
        + '<div class="news_detail_cont"><p>' + BODY
        + '</p><script>untrusted_script()</script><a href="https://example.org/guide">안내</a>'
        + '</div><footer>unrelated footer</footer></html>').encode()


def test_capture_requires_body_before_exposing_candidate(tmp_path: Path) -> None:
    # Given a real-shaped public feed and article, with unrelated scripts/footer.
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return HTML if url == URL else FEED

    # When capturing an immutable source pool and replaying it.
    first = cli.capture_sources(tmp_path, NOW, fetch)
    second = cli.capture_sources(tmp_path, NOW, fetch)
    # Then the available pool contains the article body, not executable/boilerplate text.
    assert first == second
    assert len(calls) == 2
    assert BODY.strip() in first
    assert 'untrusted_script' not in first and 'unrelated footer' not in first
    assert 'https://example.org/guide' in first


@pytest.mark.parametrize('page', [b'<html>Access denied</html>', b'<html><h1>News list</h1></html>'])
def test_http_success_without_article_is_not_candidate(tmp_path: Path, page: bytes) -> None:
    # Given HTTP-success pages without the intended article body.
    def fetch(url: str) -> bytes:
        return page if url == URL else FEED

    # When collecting, then no approved source pool is fabricated from the response.
    with pytest.raises(PreparationError, match='readable_source_pool_empty'):
        _ = cli.capture_sources(tmp_path, NOW, fetch)
    assert not (tmp_path / 'source-pool.json').exists()


def test_feed_cannot_request_unapproved_destination(tmp_path: Path) -> None:
    # Given an untrusted feed containing a loopback destination.
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return FEED.replace(URL.encode(), b'https://127.0.0.1/private')

    # When collecting, then the destination is rejected before any request.
    with pytest.raises(PreparationError, match='readable_source_pool_empty'):
        _ = cli.capture_sources(tmp_path, NOW, fetch)
    assert len(calls) == 1


def test_candidates_outside_collected_pool_are_not_supplied(tmp_path: Path) -> None:
    # Given readable primary text and model research about another source.
    pool = cli.capture_sources(tmp_path, NOW, lambda url: HTML if url == URL else FEED)
    research = parse_research(research_response(), FIXTURE_NOW)
    # When binding candidates, then inaccessible/uncollected primary evidence cannot advance.
    with pytest.raises(PreparationError, match='candidate_outside_source_pool'):
        _ = source_pool.bind_sources(research, pool)


def test_collected_body_reaches_candidate_evidence(tmp_path: Path) -> None:
    # Given model research whose primary URL matches the captured body.
    pool = cli.capture_sources(tmp_path, NOW, lambda url: HTML if url == URL else FEED)
    research = parse_research(research_response().replace('https://example.org/official', URL), FIXTURE_NOW)
    # When binding, then the independently reviewable snapshot travels with the candidate.
    bound = source_pool.bind_sources(research, pool)
    assert len(bound.candidates) == len(research.candidates)
    assert bound.candidates[0].evidence.get('source_snapshots') is not None


def test_collected_pool_reaches_reviewed_package_and_replays(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()
    html = HTML.replace(b'2026.09.23.', b'2026.09.20.')
    feed = FEED.replace(b'Wed, 23 Sep', b'Sun, 20 Sep')
    pool = cli.capture_sources(run.directory, FIXTURE_NOW, lambda url: html if url == URL else feed)
    _ = (run.directory / 'input.json').write_text(json.dumps({'run_id': run.run_id,
        'cutoff': FIXTURE_NOW.isoformat(), 'signals': 'fixture', 'history': 'fixture history',
        'source_pool_sha256': sha256(pool.encode()).hexdigest()}))

    def provider(request: StageRequest) -> StageResponse:
        response = fixture(request)
        return StageResponse(response.response.replace('https://example.org/official', URL),
                             response.session_id, response.tool_kinds)

    package = runner.execute(run, provider)
    assert BODY.strip() in (package / 'evidence.md').read_text()
    replay = FixtureProvider()
    assert runner.execute(run, replay) == package
    assert replay.calls == []


def test_changed_pool_stops_before_model_calls(tmp_path: Path) -> None:
    run, fixture = prepared_run(tmp_path), FixtureProvider()
    _ = (run.directory / 'input.json').write_text(json.dumps({'run_id': run.run_id,
        'cutoff': FIXTURE_NOW.isoformat(), 'signals': 'fixture', 'history': 'fixture history',
        'source_pool_sha256': '0' * 64}))
    _ = (run.directory / 'source-pool.json').write_text('{}')
    with pytest.raises(PreparationError, match='source_snapshot_changed'):
        _ = runner.execute(run, fixture)
    assert fixture.calls == []
