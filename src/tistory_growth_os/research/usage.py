from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Literal


@dataclass(frozen=True, slots=True)
class UsageError(ValueError):
    code: str


@dataclass(frozen=True, slots=True)
class Usage:
    receipt_id: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if (not self.receipt_id or min(self.input_tokens, self.cached_input_tokens, self.output_tokens) < 0
                or self.cached_input_tokens > self.input_tokens):
            raise UsageError('invalid_usage')


@dataclass(frozen=True, slots=True)
class MeteredRun:
    input_digest: str
    phase: str
    rubric: str
    quality_passed: bool
    model: str
    measurement: Literal['provider_usage', 'fixture', 'estimate']
    calls: tuple[Usage, ...] | None

    def __post_init__(self) -> None:
        if (re.fullmatch('[0-9a-f]{64}', self.input_digest) is None
                or not all((self.phase, self.rubric, self.model))):
            raise UsageError('invalid_run_identity')
        if self.calls is not None and len({call.receipt_id for call in self.calls}) != len(self.calls):
            raise UsageError('duplicate_receipt')


@dataclass(frozen=True, slots=True)
class RateCard:
    rate_id: str
    model: str
    unit: str
    input_per_million: Decimal
    cached_per_million: Decimal
    output_per_million: Decimal

    def __post_init__(self) -> None:
        rates = (self.input_per_million, self.cached_per_million, self.output_per_million)
        if not all((self.rate_id, self.model, self.unit)) or any(not rate.is_finite() or rate < 0 for rate in rates):
            raise UsageError('invalid_rates')


@dataclass(frozen=True, slots=True)
class UsageComparison:
    saved_tokens: int | None
    saved_fraction: Decimal | None
    reason: str


def usage_cost(run: MeteredRun, rates: RateCard) -> Decimal | None:
    if run.calls is None or run.model != rates.model:
        return None
    return sum((Decimal(call.input_tokens - call.cached_input_tokens) * rates.input_per_million
        + Decimal(call.cached_input_tokens) * rates.cached_per_million
        + Decimal(call.output_tokens) * rates.output_per_million for call in run.calls), Decimal(0)) / 1_000_000


def compare_runs(baseline: MeteredRun, optimized: MeteredRun) -> UsageComparison:
    if (baseline.input_digest, baseline.phase, baseline.rubric) != (
            optimized.input_digest, optimized.phase, optimized.rubric):
        return UsageComparison(None, None, 'unmatched_experiment')
    if not baseline.quality_passed or not optimized.quality_passed:
        return UsageComparison(None, None, 'quality_required')
    if baseline.measurement != 'provider_usage' or optimized.measurement != 'provider_usage':
        return UsageComparison(None, None, 'measured_receipts_required')
    if baseline.calls is None or optimized.calls is None:
        return UsageComparison(None, None, 'usage_unknown')
    before = sum(call.input_tokens + call.output_tokens for call in baseline.calls)
    after = sum(call.input_tokens + call.output_tokens for call in optimized.calls)
    if before == 0:
        return UsageComparison(None, None, 'zero_baseline')
    return UsageComparison(before - after, Decimal(before - after) / Decimal(before), 'comparable')
