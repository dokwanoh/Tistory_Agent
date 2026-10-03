from __future__ import annotations

from pathlib import Path

from tistory_growth_os.contracts.json_decode import JsonDecodeError
from tistory_growth_os.domain.content import OfflineRunRequest

from .catalog import PolicyCatalogError, load_policy_catalogs
from .evaluator import evaluate_catalogs
from .models import (
    GATES,
    GateCode,
    GateName,
    GateOutcome,
    PolicyBoundary,
    PolicyContext,
    PolicyEvaluation,
    PolicyGateResult,
)

__all__ = [
    "GateCode",
    "GateName",
    "GateOutcome",
    "PolicyBoundary",
    "PolicyContext",
    "PolicyEvaluation",
    "PolicyGateResult",
    "evaluate_policy",
]


def evaluate_policy(
    root: Path,
    request: OfflineRunRequest,
    context: PolicyContext | None = None,
) -> PolicyEvaluation:
    active_context = context if context is not None else PolicyContext()
    try:
        catalogs = load_policy_catalogs(root)
    except (JsonDecodeError, OSError, PolicyCatalogError):
        return PolicyEvaluation(tuple(_unavailable_result(gate) for gate in GATES))
    return PolicyEvaluation(evaluate_catalogs(catalogs, request, active_context))


def _unavailable_result(gate: GateName) -> PolicyGateResult:
    return PolicyGateResult(
        gate,
        GateOutcome.BLOCK,
        GateCode.POLICY_EVIDENCE_REQUIRED,
        "/contracts",
        (),
    )
