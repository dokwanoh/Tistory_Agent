from datetime import timedelta
import json
from pathlib import Path
from typing import TypedDict

from ..artifacts.layout import safe_output_root
from ..contracts.json_decode import parse_json
from ..domain.common import Fields, array, as_object, boolean, datetime_value, text
from ..research.intake import FEED_URL, MAX_BYTES, SignalBatch, parse_feed, public_source_url
from .contracts import PreparationError
from .package import write_immutable


class SignalMetric(TypedDict):
    query: str
    traffic_floor: int | None
    volume_percentile: float | None
    floor_change_per_hour: float | None
    observation_hours: float | None
    episode_started_at: str


def signal_metrics(current: SignalBatch, prior: SignalBatch | None) -> list[SignalMetric]:
    volumes = [lead.traffic_floor for lead in current.leads if lead.traffic_floor is not None]
    previous = {lead.lead_id: lead for lead in prior.leads} if prior else {}
    hours = (current.collected_at - prior.collected_at).total_seconds() / 3600 if prior else 0
    metrics: list[SignalMetric] = []
    for lead in current.leads:
        old = previous.get(lead.lead_id)
        velocity = None
        if (old and old.signal_at == lead.signal_at and 0 < hours <= 24
                and old.traffic_floor is not None and lead.traffic_floor is not None):
            velocity = (lead.traffic_floor - old.traffic_floor) / hours
        floor = lead.traffic_floor
        percentile = 100 * sum(v <= floor for v in volumes) / len(volumes) if floor is not None and volumes else None
        metrics.append(SignalMetric(query=lead.query, traffic_floor=floor, volume_percentile=percentile,
            floor_change_per_hour=velocity, observation_hours=hours if velocity is not None else None,
            episode_started_at=lead.signal_at.isoformat()))
    return metrics


def snapshot_context(directory: Path) -> str:
    destination = directory / 'opportunity-context.json'
    if destination.exists():
        return destination.read_text()
    fields = Fields(as_object(parse_json((directory / 'input.json').read_text()), ''), '', ())
    cutoff = datetime_value(fields, 'cutoff')
    rss = directory / 'signals.rss'
    current = parse_feed(rss.read_bytes(), cutoff) if rss.exists() else None
    prior: SignalBatch | None = None
    if current:
        for path in directory.parent.glob('*/signals.rss'):
            if path.parent == directory:
                continue
            _ = safe_output_root(directory.parent, path.relative_to(directory.parent).as_posix())
            initial = path.parent / 'input.json'
            if not initial.is_file() or path.stat().st_size > MAX_BYTES:
                continue
            earlier = Fields(as_object(parse_json(initial.read_text()), ''), '', ())
            stamp = datetime_value(earlier, 'cutoff')
            if (timedelta(0) < cutoff - stamp <= timedelta(hours=24)
                    and (prior is None or stamp > prior.collected_at)):
                prior = parse_feed(path.read_bytes(), stamp)
    payload = json.dumps({'source': FEED_URL, 'observed_at': cutoff.isoformat(),
        'current_sha256': current.input_digest if current else None,
        'previous_sha256': prior.input_digest if prior else None,
        'previous_observed_at': prior.collected_at.isoformat() if prior else None,
        'limitations': 'KR RSS approximate traffic buckets, not exact monthly volume. '
        + 'Bucket change/hour is a proxy, not actual search velocity; rolling windows can decline. '
        + 'Percentile compares only this observed feed, not all searches. Missing values are unknown.',
        'signals': signal_metrics(current, prior) if current else []}, ensure_ascii=False)
    write_immutable(destination, payload.encode())
    return payload


def competition(source: str) -> float | None:
    fields = Fields(as_object(parse_json('{"results":' + source + '}'), ''), '', ())
    results = array(fields, 'results', False)
    if len(results) > 10:
        raise PreparationError('competitor_sample_limit')
    urls: set[str] = set()
    direct = 0
    for raw in results:
        row = Fields.parse(raw, '/results', ('url', 'answers_question', 'support'))
        url = text(row, 'url')
        if not public_source_url(url):
            raise PreparationError('competitor_url_invalid')
        if url in urls:
            raise PreparationError('duplicate_competitor_url')
        urls.add(url)
        _ = text(row, 'support')
        direct += int(boolean(row, 'answers_question'))
    return 100 * direct / len(urls) if len(urls) >= 3 else None
