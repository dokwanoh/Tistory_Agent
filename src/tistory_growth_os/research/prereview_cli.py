import argparse
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from ..contracts.json_decode import JsonDecodeError, parse_json
from ..domain.common import Fields, array, boolean, text
from .intake import MAX_BYTES, IntakeError, parse_feed
from .prereview import MODEL, RUBRIC, ReviewInput, build_prompt, parse_completion
from .usage import UsageError


class Arguments(argparse.Namespace):
    feed: str = ''
    as_of: str = ''
    variant: str = 'compact'
    output: str = ''
    execute: bool = False


def check_response(response: str, queries: tuple[str, ...]) -> int:
    root = Fields.parse(parse_json(response), '', ('publication_eligible', 'candidates'))
    if boolean(root, 'publication_eligible'):
        raise UsageError('publication_forbidden')
    seen: set[str] = set()
    for value in array(root, 'candidates', True):
        item = Fields.parse(value, '/candidates',
            ('query', 'reader_question', 'rationale', 'missing_evidence', 'event_verified'))
        query = text(item, 'query')
        if query not in queries or query in seen or boolean(item, 'event_verified'):
            raise UsageError('candidate_not_supported')
        seen.add(query)
        for key in ('reader_question', 'rationale', 'missing_evidence'):
            _ = text(item, key)
    if len(seen) > 5:
        raise UsageError('candidate_limit')
    return len(seen)


def main() -> int:
    parser = argparse.ArgumentParser(description='Opt-in Astra text-only signal pre-review; no publication.')
    _ = parser.add_argument('--feed', required=True)
    _ = parser.add_argument('--as-of', required=True, help='Shared timezone-aware experiment cutoff')
    _ = parser.add_argument('--variant', choices=('raw', 'compact'), default='compact')
    _ = parser.add_argument('--output', required=True, help='New local report path; existing attempts cannot repeat')
    _ = parser.add_argument('--execute', action='store_true', help='Consume existing Codex account usage once')
    args = parser.parse_args(namespace=Arguments())
    try:
        output = Path(args.output)
        attempt = output.with_suffix('.attempt.json')
        if output.exists() or attempt.exists() or output.suffix != '.json':
            raise UsageError('new_run_path_required')
        with Path(args.feed).open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        batch = parse_feed(raw, datetime.fromisoformat(args.as_of))
        if not batch.leads:
            raise UsageError('research_leads_required')
        prompt = build_prompt(ReviewInput(batch, raw, args.variant == 'compact'))
        if len(prompt.encode()) > 100_000:
            raise UsageError('prompt_size_limit')
        identity = sha256(raw + batch.collected_at.isoformat().encode()).hexdigest()
        if not args.execute:
            print(json.dumps({'state': 'dry_run', 'model': MODEL, 'input_digest': identity,
                'variant': args.variant, 'prompt_bytes': len(prompt.encode()), 'model_calls': 0}))
            return 0
        with attempt.open('x') as stream:
            _ = stream.write(json.dumps({'model': MODEL, 'input_digest': identity, 'variant': args.variant,
                'prompt_digest': sha256(prompt.encode()).hexdigest(), 'state': 'attempted'}))
        schema = Path(__file__).resolve().parents[3] / 'contracts/schemas/signal-prereview.schema.json'
        started = perf_counter()
        result = subprocess.run(['codex', 'exec', '--json', '--ephemeral', '--sandbox', 'read-only',
            '--model', MODEL, '--output-schema', str(schema), '-'], input=prompt,
            text=True, capture_output=True, check=False, timeout=240)
        if result.returncode != 0:
            diagnostic = result.stderr.lower()
            flags = [name for name in ('trust', 'hook', 'sandbox', 'permission', 'schema',
                'model', 'authentication', 'unauthorized', 'config', 'network', 'login', 'quota')
                if name in diagnostic]
            with output.open('x') as stream:
                _ = stream.write(json.dumps({'state': 'held', 'exit_code': result.returncode,
                    'diagnostic_flags': flags, 'stderr_sha256': sha256(result.stderr.encode()).hexdigest(),
                    'stderr_bytes': len(result.stderr.encode()), 'usage': None, 'publish_eligible': False}))
            print(json.dumps({'state': 'provider_failed', 'exit_code': result.returncode,
                'diagnostic_flags': flags}), file=sys.stderr)
            raise UsageError('codex_execution_failed')
        usage, response = parse_completion(result.stdout)
        candidates = check_response(response, tuple(lead.query for lead in batch.leads))
        report = {'state': 'prereview_completed', 'publish_eligible': False,
            'structural_check': True, 'candidate_count': candidates, 'review_response': response,
            'elapsed_seconds': round(perf_counter() - started, 3),
            'receipt': {'schema_version': 'metered-run-v1', 'input_digest': identity,
                'phase': 'signal_prereview', 'rubric': RUBRIC, 'quality_passed': False,
                'model': MODEL, 'measurement': 'provider_usage', 'calls': [asdict(usage)]},
            'quality_note': 'Independent semantic assessment required; structural checks are not editorial approval.',
            'cost': None, 'billing_basis': 'existing_codex_account_not_api_invoice'}
        with output.open('x') as stream:
            _ = stream.write(json.dumps(report, ensure_ascii=False) + '\n')
        print(json.dumps({'state': report['state'], 'candidate_count': candidates,
            'usage': asdict(usage), 'report': str(output), 'publish_eligible': False}))
        return 0
    except (OSError, ValueError, JsonDecodeError, subprocess.TimeoutExpired) as error:
        reason = error.code if isinstance(error, (UsageError, IntakeError)) else type(error).__name__
        print(json.dumps({'state': 'held', 'reason': reason, 'publish_eligible': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
