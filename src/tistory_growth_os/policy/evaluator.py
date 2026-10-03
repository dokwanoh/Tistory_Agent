from __future__ import annotations

from tistory_growth_os.domain.common import DisclosureBasis
from tistory_growth_os.domain.content import OfflineRunRequest
from tistory_growth_os.domain.ids import OwnerDecisionId

from .catalog import OwnerDecisionCatalog, PolicyCatalog, PolicyCatalogError, PolicyCatalogs, PolicyClaim
from .models import (
    GATES,
    REQUIRED_CONTROLS,
    GateCode,
    GateName,
    GateOutcome,
    PolicyBoundary,
    PolicyContext,
    PolicyGateResult,
)


def evaluate_catalogs(
    catalogs: PolicyCatalogs,
    request: OfflineRunRequest,
    context: PolicyContext,
) -> tuple[PolicyGateResult, ...]:
    return tuple(
        _evaluate_gate(gate, catalogs.policy, catalogs.owner_decisions, request, context)
        for gate in GATES
    )


def _evaluate_gate(
    gate: GateName,
    catalog: PolicyCatalog,
    owners: OwnerDecisionCatalog,
    request: OfflineRunRequest,
    context: PolicyContext,
) -> PolicyGateResult:
    claims = _claims_for_gate(catalog, gate)
    missing = tuple(claim for claim in claims if not claim.evidence_is_complete)
    if missing:
        return _evidence_required(gate, missing)
    result = _gate_specific(gate, catalog, owners, request, context, claims)
    if result is not None:
        return result
    return PolicyGateResult(
        gate,
        GateOutcome.PASS,
        GateCode.POLICY_CHECKED,
        f"/gates/{gate}",
        tuple(claim.claim_id for claim in claims),
    )


def _claims_for_gate(catalog: PolicyCatalog, gate: GateName) -> tuple[PolicyClaim, ...]:
    for candidate, controls in REQUIRED_CONTROLS:
        if candidate is gate:
            return tuple(catalog.claim_for_control(control) for control in controls)
    raise PolicyCatalogError("/gates", f"missing controls for {gate}")


def _gate_specific(
    gate: GateName,
    catalog: PolicyCatalog,
    owners: OwnerDecisionCatalog,
    request: OfflineRunRequest,
    context: PolicyContext,
    claims: tuple[PolicyClaim, ...],
) -> PolicyGateResult | None:
    match gate:
        case GateName.TISTORY:
            return _tistory_result(catalog, owners, request, context, claims)
        case GateName.KFTC_DISCLOSURE:
            return _disclosure_result(request, context, claims)
        case GateName.PRIVACY | GateName.TELEMETRY:
            return _private_boundary_result(gate, owners, context, claims)
        case GateName.GOOGLE_SEARCH | GateName.NAVER_SEARCH | GateName.ADSENSE:
            return None


def _tistory_result(
    catalog: PolicyCatalog,
    owners: OwnerDecisionCatalog,
    request: OfflineRunRequest,
    context: PolicyContext,
    claims: tuple[PolicyClaim, ...],
) -> PolicyGateResult | None:
    prohibited = set(catalog.prohibited_ad_formats)
    for index, ad_format in enumerate(context.ad_formats):
        if ad_format in prohibited:
            return PolicyGateResult(
                GateName.TISTORY,
                GateOutcome.BLOCK,
                GateCode.PROHIBITED_AD_FORMAT,
                f"/context/ad_formats/{index}",
                ("CL-010",),
            )
    match context.boundary:
        case PolicyBoundary.OFFLINE_SYNTHETIC:
            return _offline_owner_result(owners, request, claims)
        case PolicyBoundary.LIVE_EXTERNAL:
            return _owner_required(
                GateName.TISTORY,
                claims,
                (OwnerDecisionId("ODR-001"), OwnerDecisionId("ODR-006")),
                "/context/boundary",
            )
        case PolicyBoundary.PRIVATE_TELEMETRY:
            return None


def _offline_owner_result(
    owners: OwnerDecisionCatalog,
    request: OfflineRunRequest,
    claims: tuple[PolicyClaim, ...],
) -> PolicyGateResult | None:
    for decision_id in request.owner_decision_ids:
        decision = owners.decision(decision_id)
        if not decision.offline_fixture_allowed:
            return _owner_required(
                GateName.TISTORY,
                claims,
                (decision_id,),
                "/owner_decision_ids",
            )
    return None


def _private_boundary_result(
    gate: GateName,
    owners: OwnerDecisionCatalog,
    context: PolicyContext,
    claims: tuple[PolicyClaim, ...],
) -> PolicyGateResult | None:
    match context.boundary:
        case PolicyBoundary.OFFLINE_SYNTHETIC | PolicyBoundary.LIVE_EXTERNAL:
            return None
        case PolicyBoundary.PRIVATE_TELEMETRY:
            return _private_owner_result(gate, owners, claims)


def _private_owner_result(
    gate: GateName,
    owners: OwnerDecisionCatalog,
    claims: tuple[PolicyClaim, ...],
) -> PolicyGateResult | None:
    match gate:
        case GateName.PRIVACY:
            decisions = (OwnerDecisionId("ODR-001"), OwnerDecisionId("ODR-005"))
        case GateName.TELEMETRY:
            decisions = (OwnerDecisionId("ODR-001"),)
        case GateName.GOOGLE_SEARCH | GateName.NAVER_SEARCH | GateName.ADSENSE | GateName.TISTORY | GateName.KFTC_DISCLOSURE:
            return None
    for decision_id in decisions:
        if not owners.decision(decision_id).external_write_allowed:
            return _owner_required(gate, claims, decisions, "/context/boundary")
    return None


def _disclosure_result(
    request: OfflineRunRequest,
    context: PolicyContext,
    claims: tuple[PolicyClaim, ...],
) -> PolicyGateResult | None:
    if _disclosure_required(request.disclosure.basis, context) and (
        not request.disclosure.required or not request.disclosure.text
    ):
        return PolicyGateResult(
            GateName.KFTC_DISCLOSURE,
            GateOutcome.BLOCK,
            GateCode.DISCLOSURE_REQUIRED,
            "/disclosure",
            tuple(claim.claim_id for claim in claims),
        )
    return None


def _disclosure_required(basis: DisclosureBasis, context: PolicyContext) -> bool:
    match basis:
        case DisclosureBasis.NONE:
            return context.economic_interest_required or context.ai_virtual_person_endorsement
        case DisclosureBasis.ADVERTISING | DisclosureBasis.AFFILIATE | DisclosureBasis.SPONSORSHIP | DisclosureBasis.AI_VIRTUAL_PERSON:
            return True


def _evidence_required(gate: GateName, missing: tuple[PolicyClaim, ...]) -> PolicyGateResult:
    first = missing[0]
    return PolicyGateResult(
        gate,
        GateOutcome.BLOCK,
        GateCode.POLICY_EVIDENCE_REQUIRED,
        f"/claims/{first.claim_id}",
        tuple(item.claim_id for item in missing),
    )


def _owner_required(
    gate: GateName,
    claims: tuple[PolicyClaim, ...],
    decisions: tuple[OwnerDecisionId, ...],
    path: str,
) -> PolicyGateResult:
    return PolicyGateResult(
        gate,
        GateOutcome.OWNER_DECISION_REQUIRED,
        GateCode.OWNER_DECISION_REQUIRED,
        path,
        tuple(claim.claim_id for claim in claims),
        decisions,
    )
