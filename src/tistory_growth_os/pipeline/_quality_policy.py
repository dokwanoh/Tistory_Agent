from __future__ import annotations

from tistory_growth_os.domain.publishing import (
    FindingCode,
    FindingSeverity,
    QualityFinding,
)
from tistory_growth_os.policy.gates import (
    GateCode,
    GateOutcome,
    PolicyEvaluation,
)


PolicyInput = tuple[QualityFinding, ...] | PolicyEvaluation


def normalize_policy_findings(value: PolicyInput) -> tuple[QualityFinding, ...]:
    match value:
        case PolicyEvaluation(outcomes=outcomes):
            return tuple(
                finding
                for outcome in outcomes
                if (finding := _policy_finding(outcome.outcome, outcome.code, outcome.path))
                is not None
            )
        case tuple() as findings:
            return findings


def _policy_finding(
    outcome: GateOutcome,
    code: GateCode,
    path: str,
) -> QualityFinding | None:
    match outcome:
        case GateOutcome.PASS:
            return None
        case GateOutcome.BLOCK | GateOutcome.UNKNOWN | GateOutcome.OWNER_DECISION_REQUIRED:
            finding_code = _finding_code(code)
            return QualityFinding(
                finding_code,
                FindingSeverity.ERROR,
                path,
                f"policy outcome {outcome.value}: {code.value}",
            )


def _finding_code(code: GateCode) -> FindingCode:
    match code:
        case GateCode.PROHIBITED_AD_FORMAT:
            return FindingCode.PROHIBITED_AD_FORMAT
        case GateCode.DISCLOSURE_REQUIRED:
            return FindingCode.DISCLOSURE_REQUIRED
        case GateCode.POLICY_CHECKED | GateCode.POLICY_EVIDENCE_REQUIRED | GateCode.OWNER_DECISION_REQUIRED:
            return FindingCode.POLICY_EVIDENCE_REQUIRED
