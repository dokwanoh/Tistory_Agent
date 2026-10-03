import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys

from ..contracts.json_ast import JsonNull, JsonNumber
from ..contracts.json_decode import JsonDecodeError, parse_json
from ..domain.common import Fields, array, boolean, fail, literal, text
from .usage import MeteredRun, RateCard, Usage, UsageError, compare_runs, usage_cost


def count(fields: Fields, key: str) -> int:
    value = fields.required(key)
    if isinstance(value, JsonNumber) and isinstance(value.value, int) and value.value >= 0:
        return value.value
    fail(fields.child(key), 'type', 'nonnegative integer required')


def parse_run(source: str) -> MeteredRun:
    fields = Fields.parse(parse_json(source), '', ('schema_version', 'input_digest', 'phase', 'rubric',
        'quality_passed', 'model', 'measurement', 'calls'))
    _ = literal(fields, 'schema_version', 'metered-run-v1')
    kind = text(fields, 'measurement')
    if kind != 'provider_usage' and kind != 'fixture' and kind != 'estimate':
        raise UsageError('measurement_kind_invalid')
    calls: tuple[Usage, ...] | None = None
    if not isinstance(fields.required('calls'), JsonNull):
        parsed: list[Usage] = []
        for index, value in enumerate(array(fields, 'calls', False)):
            entry = Fields.parse(value, f'/calls/{index}',
                ('receipt_id', 'input_tokens', 'cached_input_tokens', 'output_tokens'))
            parsed.append(Usage(text(entry, 'receipt_id'), count(entry, 'input_tokens'),
                count(entry, 'cached_input_tokens'), count(entry, 'output_tokens')))
        calls = tuple(parsed)
    return MeteredRun(text(fields, 'input_digest'), text(fields, 'phase'), text(fields, 'rubric'),
        boolean(fields, 'quality_passed'), text(fields, 'model'), kind, calls)


def parse_rates(source: str) -> RateCard:
    fields = Fields.parse(parse_json(source), '', ('schema_version', 'rate_id', 'model', 'unit',
        'input_per_million', 'cached_per_million', 'output_per_million'))
    _ = literal(fields, 'schema_version', 'rate-card-v1')
    return RateCard(text(fields, 'rate_id'), text(fields, 'model'), text(fields, 'unit'),
        Decimal(text(fields, 'input_per_million')), Decimal(text(fields, 'cached_per_million')),
        Decimal(text(fields, 'output_per_million')))


class Arguments(argparse.Namespace):
    baseline: str = ''
    optimized: str = ''
    rates: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description='Compare trusted local metering receipts; never calls a model.')
    _ = parser.add_argument('baseline')
    _ = parser.add_argument('optimized')
    _ = parser.add_argument('--rates', help='Explicit same-model rate card; no default or inferred prices')
    args = parser.parse_args(namespace=Arguments())
    try:
        baseline = parse_run(Path(args.baseline).read_text())
        optimized = parse_run(Path(args.optimized).read_text())
        comparison = compare_runs(baseline, optimized)
        rates = parse_rates(Path(args.rates).read_text()) if args.rates is not None else None
        before = usage_cost(baseline, rates) if rates is not None else None
        after = usage_cost(optimized, rates) if rates is not None else None
        saved = before - after if before is not None and after is not None and comparison.saved_tokens is not None else None
        print(json.dumps({'state': comparison.reason, 'saved_tokens': comparison.saved_tokens,
            'saved_token_fraction': str(comparison.saved_fraction) if comparison.saved_fraction is not None else None,
            'baseline_modeled_cost': str(before) if before is not None else None,
            'optimized_modeled_cost': str(after) if after is not None else None,
            'saved_cost': str(saved) if saved is not None else None,
            'cost_unit': rates.unit if rates is not None else None,
            'rate_id': rates.rate_id if rates is not None else None,
            'billing_note': 'Modeled token cost only; not an invoice, excludes tools/images/compute/development.'}))
        return 0 if comparison.saved_tokens is not None else 2
    except (JsonDecodeError, UsageError, OSError, InvalidOperation) as error:
        print(json.dumps({'state': 'invalid_receipt', 'error_type': type(error).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
