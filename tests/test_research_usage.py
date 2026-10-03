from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tistory_growth_os.research.usage import Usage, MeteredRun, RateCard, compare_runs, usage_cost


def run() -> MeteredRun:
    return MeteredRun('a' * 64, 'topic_review', 'rubric-v1', True, 'fixture-model',
                      'provider_usage', (Usage('call1', 1000, 400, 100),))


def test_cost_when_cached_input_is_a_subset() -> None:
    # Given: 1000 total input, including 400 cached tokens.
    rates = RateCard('test-only-v1', 'fixture-model', 'test-unit', Decimal(10), Decimal(1), Decimal(20))
    # When: pricing counts uncached input and output once.
    cost = usage_cost(run(), rates)
    # Then: no double billing cached input or reasoning output.
    assert cost == Decimal('0.0084')


@pytest.mark.parametrize('change', ['input', 'quality', 'rubric', 'missing', 'fixture'])
def test_comparison_when_runs_are_not_comparable(change: str) -> None:
    # Given: unmatched data, failed quality, or unobserved usage.
    baseline = run()
    variants = {'input': replace(baseline, input_digest='b' * 64),
        'quality': replace(baseline, quality_passed=False),
        'rubric': replace(baseline, rubric='different'),
        'missing': replace(baseline, calls=None),
        'fixture': replace(baseline, measurement='fixture')}
    # When: compare against the actual provider baseline.
    result = compare_runs(baseline, variants[change])
    # Then: no invented percentage.
    assert result.saved_tokens is None and result.saved_fraction is None


def test_comparison_when_both_runs_pass_same_task() -> None:
    # Given: equal input/rubric, with fewer tokens and a billed retry included.
    baseline = run()
    optimized = replace(baseline, calls=(Usage('call2', 200, 0, 20), Usage('retry', 100, 0, 10)))
    # When: sum every call including failed/retried requests.
    result = compare_runs(baseline, optimized)
    # Then: input+output totals, cached input not counted twice.
    assert result.saved_tokens == 770
    assert result.saved_fraction == Decimal('0.7')


@pytest.mark.parametrize('usage', [(100, 101, 0), (-1, 0, 0), (1, 0, -1)])
def test_usage_when_provider_numbers_are_invalid(usage: tuple[int, int, int]) -> None:
    # Given / When / Then: invalid receipt totals are rejected at construction.
    with pytest.raises(ValueError):
        _ = Usage('bad', *usage)


def test_usage_when_receipt_is_repeated() -> None:
    # Given / When / Then: duplicate provider receipt cannot inflate savings baseline.
    with pytest.raises(ValueError):
        _ = replace(run(), calls=(Usage('same', 1, 0, 1), Usage('same', 1, 0, 1)))


def test_usage_cli_when_provider_receipts_and_rates_are_supplied(tmp_path: Path) -> None:
    # Given: synthetic provider-shaped records; fixture prices are not real billing.
    receipt = {'schema_version': 'metered-run-v1', 'input_digest': 'a' * 64,
        'phase': 'topic_review', 'rubric': 'v1', 'quality_passed': True,
        'model': 'fixture-model', 'measurement': 'provider_usage', 'calls': [
            {'receipt_id': 'one', 'input_tokens': 1000, 'cached_input_tokens': 400, 'output_tokens': 100}]}
    before = tmp_path / 'before.json'
    after = tmp_path / 'after.json'
    _ = before.write_text(json.dumps(receipt))
    receipt['calls'] = [{'receipt_id': 'two', 'input_tokens': 200, 'cached_input_tokens': 0, 'output_tokens': 20}]
    _ = after.write_text(json.dumps(receipt))
    rates = tmp_path / 'rates.json'
    _ = rates.write_text(json.dumps({'schema_version': 'rate-card-v1', 'rate_id': 'test-v1',
        'model': 'fixture-model', 'unit': 'test-unit', 'input_per_million': '10',
        'cached_per_million': '1', 'output_per_million': '20'}))
    # When: the comparison runs through a separate command process.
    result = subprocess.run([sys.executable, '-m', 'tistory_growth_os.research.usage_cli',
        str(before), str(after), '--rates', str(rates)], capture_output=True, text=True, check=False)
    # Then: exact token and modeled-cost deltas include the cache discount.
    assert result.returncode == 0, result.stderr
    assert '"saved_tokens": 880' in result.stdout
    assert '"saved_cost": "0.0060"' in result.stdout


def test_run_parser_when_usage_is_unknown() -> None:
    # Given: a valid local run identity but provider usage not returned.
    from tistory_growth_os.research.usage_cli import parse_run
    raw = json.dumps({'schema_version': 'metered-run-v1', 'input_digest': 'a' * 64,
        'phase': 'topic_review', 'rubric': 'v1', 'quality_passed': True,
        'model': 'fixture-model', 'measurement': 'provider_usage', 'calls': None})
    # When / Then: null survives parsing; no synthetic zero-cost measurement.
    assert parse_run(raw).calls is None
