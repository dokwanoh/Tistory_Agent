import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from .intake import FEED_URL, MAX_BYTES, IntakeError, parse_feed, review_packet


class Arguments(argparse.Namespace):
    feed: str | None = None
    live: bool = False
    as_of: str | None = None
    output: str | None = None


def collect_live() -> bytes:
    result = subprocess.run(['/usr/bin/curl', '--disable', '--fail', '--silent', '--show-error',
        '--proto', '=https', '--connect-timeout', '5', '--max-time', '20', '--max-filesize', str(MAX_BYTES),
        '--write-out', '\n%{http_code}', FEED_URL], capture_output=True, check=False, timeout=25)
    body, _, status = result.stdout.rpartition(b'\n')
    if result.returncode != 0 or status != b'200':
        raise IntakeError('public_feed_fetch_failed')
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only KR trend signals; no LLM or publisher calls.')
    group = parser.add_mutually_exclusive_group(required=True)
    _ = group.add_argument('--feed', help='Captured RSS for reproducible offline replay')
    _ = group.add_argument('--live', action='store_true', help='One bounded public Google Trends KR RSS request')
    _ = parser.add_argument('--as-of', help='Timezone-aware replay clock; offline only')
    _ = parser.add_argument('--output', help='Create a new local JSON report; refuses overwrite')
    args = parser.parse_args(namespace=Arguments())
    started = perf_counter()
    try:
        if args.output is not None and (Path(args.output).exists() or Path(args.output).with_suffix('.rss').exists()
                                       or Path(args.output).suffix != '.json'):
            raise IntakeError('new_json_report_required')
        if args.live and args.as_of is not None:
            raise IntakeError('live_clock_override_denied')
        if args.live:
            raw = collect_live()
        else:
            if args.feed is None:
                raise IntakeError('feed_required')
            with Path(args.feed).open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
        now = datetime.fromisoformat(args.as_of) if args.as_of is not None else datetime.now(timezone.utc)
        batch = parse_feed(raw, now)
        packet = review_packet(batch)
        result = json.dumps({'packet': packet, 'network_requests': int(args.live),
            'packet_bytes': len(json.dumps(packet, ensure_ascii=False).encode()),
            'elapsed_seconds': round(perf_counter() - started, 3),
            'usage_scope': 'intake_only_excludes_agent_development_and_editorial_review',
            'baseline_tokens': None, 'saved_tokens': None, 'saved_cost': None}, ensure_ascii=False)
        if args.output is not None:
            with Path(args.output).with_suffix('.rss').open('xb') as stream:
                _ = stream.write(raw)
            with Path(args.output).open('x', encoding='utf-8') as stream:
                _ = stream.write(result + '\n')
        print(result)
        return 0
    except (IntakeError, OSError, subprocess.TimeoutExpired, ValueError) as error:
        print(json.dumps({'state': 'held', 'error_type': type(error).__name__,
            'reason': error.code if isinstance(error, IntakeError) else 'input_or_io_failure',
            'publish_eligible': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
