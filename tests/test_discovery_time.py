from datetime import datetime
import json

import pytest

from tistory_growth_os.preparation.v2_sources import discover
from tistory_growth_os.domain.common import Fields, text


def lead(event_at: str) -> str:
    return json.dumps({'candidates': [{'id': 'recent-topic', 'title': 'Useful topic',
        'event_at': event_at, 'event_time_basis': 'Original reports this morning in Korea',
        'reader_question': 'What changed?', 'source_urls': ['https://example.org/news']} ]})


@pytest.mark.parametrize('period', ['오전', '새벽'])
def test_korean_morning_reaches_evidence_without_inventing_exact_time(period: str) -> None:
    raw = f'2026-09-24 {period}(한국시간)'
    candidates = discover(lead(raw), datetime.fromisoformat('2026-09-24T15:45:00+09:00'))
    assert len(candidates) == 1
    assert candidates[0].event_at == datetime.fromisoformat('2026-09-24T00:00:00+09:00')
    assert text(Fields(candidates[0].evidence, '', ()), 'event_at') == raw


@pytest.mark.parametrize('clock', ['2026-09-24T05:00:00+09:00', '2026-09-25T00:00:00+09:00'])
def test_approximate_range_cannot_hide_future_or_stale_boundary(clock: str) -> None:
    assert discover(lead('2026-09-24 오전(한국시간)'), datetime.fromisoformat(clock)) == ()


def test_exact_timestamp_keeps_existing_meaning() -> None:
    candidates = discover(lead('2026-09-24T09:00:00+09:00'),
                          datetime.fromisoformat('2026-09-24T15:45:00+09:00'))
    assert candidates[0].event_at.hour == 9
