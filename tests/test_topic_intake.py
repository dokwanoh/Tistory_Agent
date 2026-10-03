from datetime import datetime
from pathlib import Path
import subprocess
import sys

import pytest

from tistory_growth_os.research.intake import IntakeError, parse_feed, review_packet


NOW = datetime.fromisoformat('2030-01-02T12:00:00+09:00')


def feed(items: str) -> bytes:
    return ('<rss xmlns:ht="https://trends.google.com/trending/rss"><channel>'
            + items + '</channel></rss>').encode()


def item(title: str, stamp: str, traffic: str = '1,000+') -> str:
    return ('<item><title>' + title + '</title><pubDate>' + stamp + '</pubDate>'
            + '<ht:approx_traffic>' + traffic + '</ht:approx_traffic><ht:news_item>'
            + '<ht:news_item_url>https://example.org/news</ht:news_item_url>'
            + '</ht:news_item></item>')


def test_intake_when_duplicate_and_old_signals_exist() -> None:
    # Given: fresh repeated query, exact 24h boundary and future signal.
    raw = feed(item('AI', 'Wed, 02 Jan 2030 10:00:00 +0900')
               + item('ai', 'Wed, 02 Jan 2030 11:00:00 +0900')
               + item('old', 'Tue, 01 Jan 2030 12:00:00 +0900')
               + item('future', 'Wed, 02 Jan 2030 13:00:00 +0900'))
    # When: collection screens signal time, not event freshness.
    batch = parse_feed(raw, NOW)
    packet = review_packet(batch)
    # Then: one lead is retained, without editorial or publication approval.
    assert len(batch.leads) == 1
    assert batch.leads[0].signal_at == datetime.fromisoformat('2030-01-02T11:00:00+09:00')
    assert batch.leads[0].traffic_floor == 1000
    assert len(batch.rejections) == 3
    assert packet['state'] == 'research_required'
    assert packet['publish_eligible'] is False
    assert packet['llm_calls'] == 0
    assert packet['candidates'][0]['event_at'] is None


@pytest.mark.parametrize('raw', [b'<html/>', b'<rss>', b'<!DOCTYPE rss><rss/>',
                                 b'\xff', b'x' * 2_000_001])
def test_intake_when_feed_contract_is_invalid(raw: bytes) -> None:
    # Given / When / Then: malformed or oversized feeds never produce candidates.
    with pytest.raises(IntakeError):
        _ = parse_feed(raw, NOW)


@pytest.mark.parametrize('stamp', ['', 'yesterday', 'Wed, 02 Jan 2030 11:00:00'])
def test_intake_when_time_is_missing_or_ambiguous(stamp: str) -> None:
    # Given / When: uncertain timestamps cannot acquire an invented timezone.
    batch = parse_feed(feed(item('topic', stamp, 'unknown')), NOW)
    # Then: rejected, not fresh by crawl time.
    assert not batch.leads and len(batch.rejections) == 1


def test_intake_when_unknown_volume_and_unsafe_link_exist() -> None:
    # Given: a valid timestamp but no trustworthy popularity value or link.
    raw = feed(item('topic', 'Wed, 02 Jan 2030 11:00:00 +0900', 'unknown')).replace(
        b'https://example.org/news', b'http://127.0.0.1/private')
    # When: parse untrusted feed metadata.
    batch = parse_feed(raw, NOW)
    # Then: retain unknowns and never fetch the unsafe link.
    assert batch.leads[0].traffic_floor is None
    assert batch.leads[0].source_urls == ()


def test_cli_when_offline_feed_is_supplied(tmp_path: Path) -> None:
    # Given: deterministic captured feed and explicit replay clock.
    source = tmp_path / 'feed.xml'
    _ = source.write_bytes(feed(item('topic', 'Wed, 02 Jan 2030 11:00:00 +0900')))
    # When: invoke a fresh CLI process without a live flag.
    result = subprocess.run([sys.executable, '-m', 'tistory_growth_os.research',
        '--feed', str(source), '--as-of', NOW.isoformat()], capture_output=True, text=True, check=False)
    # Then: review handoff only, no posting or paid model execution.
    assert result.returncode == 0, result.stderr
    assert '"state": "research_required"' in result.stdout
    assert '"network_requests": 0' in result.stdout
    assert '"publish_eligible": false' in result.stdout


def test_cli_when_report_is_saved_preserves_replay_bytes(tmp_path: Path) -> None:
    # Given: captured source bytes and an unused local report path.
    source = tmp_path / 'input.xml'
    raw = feed(item('topic', 'Wed, 02 Jan 2030 11:00:00 +0900'))
    _ = source.write_bytes(raw)
    output = tmp_path / 'report.json'
    # When: save one research report.
    result = subprocess.run([sys.executable, '-m', 'tistory_growth_os.research', '--feed', str(source),
        '--as-of', NOW.isoformat(), '--output', str(output)], capture_output=True, text=True, check=False)
    # Then: exact original feed remains available for a fair before/after replay.
    assert result.returncode == 0, result.stderr
    assert output.with_suffix('.rss').read_bytes() == raw


@pytest.mark.parametrize('arguments', [[], ['--live', '--as-of', NOW.isoformat()],
    ['--feed', '/nonexistent/topic-intake-file']])
def test_cli_when_arguments_are_unsafe_or_missing(arguments: list[str]) -> None:
    # Given / When: invalid invocation must fail before a network or publisher call.
    result = subprocess.run([sys.executable, '-m', 'tistory_growth_os.research', *arguments],
                            capture_output=True, text=True, check=False)
    # Then: explicit non-success, not an empty successful topic batch.
    assert result.returncode == 2
