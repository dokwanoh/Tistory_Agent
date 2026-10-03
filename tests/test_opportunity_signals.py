from datetime import timedelta
from pathlib import Path
import json

import pytest

from tests.preparation_fixture import NOW
from tistory_growth_os.research.intake import parse_feed
from tistory_growth_os.preparation import opportunity


def feed(traffic: int, started: str = 'Mon, 21 Sep 2026 00:00:00 GMT') -> bytes:
    return (f'<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item>'
            f'<title>과학</title><pubDate>{started}</pubDate><ht:approx_traffic>{traffic}+</ht:approx_traffic>'
            '</item></channel></rss>').encode()


def test_snapshot_change_is_bucket_proxy_not_invented_search_rate() -> None:
    # Given comparable observations of the same trend episode one hour apart.
    first = parse_feed(feed(1000), NOW)
    second = parse_feed(feed(5000), NOW + timedelta(hours=1))
    # When quantitative inputs are built.
    report = opportunity.signal_metrics(second, first)[0]
    # Then actual observed thresholds and their proxy change are retained.
    assert report['traffic_floor'] == 5000
    assert report['floor_change_per_hour'] == 4000
    assert report['volume_percentile'] == 100


def test_missing_or_different_episode_has_unknown_growth() -> None:
    # Given a new episode rather than a comparable earlier observation.
    current = parse_feed(feed(5000, 'Mon, 21 Sep 2026 00:30:00 GMT'), NOW)
    prior = parse_feed(feed(1000), NOW - timedelta(minutes=15))
    # When constructing metrics, then missing comparability cannot become zero growth.
    assert opportunity.signal_metrics(current, prior)[0]['floor_change_per_hour'] is None
    assert opportunity.signal_metrics(current, None)[0]['floor_change_per_hour'] is None


def test_competition_uses_observed_sample_and_deduplicates() -> None:
    # Given four retrieved pages, two directly answering the target question.
    rows = [{'url': f'https://example.org/{n}', 'answers_question': n < 2,
             'support': 'Fixture inspection'} for n in range(4)]
    # When calculating sample competition, then its denominator is the inspected sample.
    assert opportunity.competition(json.dumps(rows)) == 50
    with pytest.raises(ValueError, match='duplicate_competitor_url'):
        _ = opportunity.competition(json.dumps(rows + rows[:1]))


def test_empty_competition_is_unknown_not_easy() -> None:
    # Given unavailable search results, when measured, then do not reward missing data.
    assert opportunity.competition('[]') is None


def test_snapshot_context_is_immutable(tmp_path: Path) -> None:
    # Given a persisted run and an RSS capture.
    run = tmp_path / '.artifacts/preparation/current'
    run.mkdir(parents=True)
    _ = (run / 'signals.rss').write_bytes(feed(5000))
    _ = (run / 'input.json').write_text(json.dumps({'cutoff': NOW.isoformat()}))
    # When building and replaying the context, then exactly the recorded bytes recur.
    first = opportunity.snapshot_context(run)
    assert opportunity.snapshot_context(run) == first
