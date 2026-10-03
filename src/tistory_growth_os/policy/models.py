from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final

from tistory_growth_os.domain.ids import OwnerDecisionId

from .catalog import PolicyCatalogError


@unique
class GateName(StrEnum):
    GOOGLE_SEARCH = "google_search"
    NAVER_SEARCH = "naver_search"
    ADSENSE = "adsense"
    TISTORY = "tistory"
    KFTC_DISCLOSURE = "kftc_disclosure"
    PRIVACY = "privacy"
    TELEMETRY = "telemetry"


@unique
class GateOutcome(StrEnum):
    PASS = "pass"
    BLOCK = "block"
    UNKNOWN = "unknown"
    OWNER_DECISION_REQUIRED = "owner_decision_required"


@unique
class GateCode(StrEnum):
    POLICY_CHECKED = "POLICY_CHECKED"
    POLICY_EVIDENCE_REQUIRED = "POLICY_EVIDENCE_REQUIRED"
    OWNER_DECISION_REQUIRED = "OWNER_DECISION_REQUIRED"
    PROHIBITED_AD_FORMAT = "PROHIBITED_AD_FORMAT"
    DISCLOSURE_REQUIRED = "DISCLOSURE_REQUIRED"


@unique
class PolicyBoundary(StrEnum):
    OFFLINE_SYNTHETIC = "offline_synthetic"
    LIVE_EXTERNAL = "live_external"
    PRIVATE_TELEMETRY = "private_telemetry"


@dataclass(frozen=True, slots=True)
class PolicyContext:
    boundary: PolicyBoundary = PolicyBoundary.OFFLINE_SYNTHETIC
    ad_formats: tuple[str, ...] = ()
    economic_interest_required: bool = False
    ai_virtual_person_endorsement: bool = False


@dataclass(frozen=True, slots=True)
class PolicyGateResult:
    gate: GateName
    outcome: GateOutcome
    code: GateCode
    path: str
    evidence_claim_ids: tuple[str, ...]
    owner_decision_ids: tuple[OwnerDecisionId, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    outcomes: tuple[PolicyGateResult, ...]

    @property
    def external_write_count(self) -> int:
        return 0

    @property
    def approval_eligible(self) -> bool:
        return all(item.outcome is GateOutcome.PASS for item in self.outcomes)

    def for_gate(self, gate: GateName) -> PolicyGateResult:
        for outcome in self.outcomes:
            if outcome.gate is gate:
                return outcome
        raise PolicyCatalogError("/outcomes", f"missing gate result {gate}")


GATES: Final[tuple[GateName, ...]] = (
    GateName.GOOGLE_SEARCH,
    GateName.NAVER_SEARCH,
    GateName.ADSENSE,
    GateName.TISTORY,
    GateName.KFTC_DISCLOSURE,
    GateName.PRIVACY,
    GateName.TELEMETRY,
)
REQUIRED_CONTROLS: Final[tuple[tuple[GateName, tuple[str, ...]], ...]] = (
    (GateName.GOOGLE_SEARCH, ("scaled_content_abuse",)),
    (GateName.NAVER_SEARCH, ("experience_enriched_originality",)),
    (GateName.ADSENSE, ("genuine_traffic",)),
    (GateName.TISTORY, ("retired_open_api_forbidden", "offline_editor_ready_package", "prohibited_ad_formats")),
    (GateName.KFTC_DISCLOSURE, ("economic_interest_disclosure", "ai_virtual_person_endorsement")),
    (GateName.PRIVACY, ("privacy_data_flow_required", "controller_unsettled")),
    (GateName.TELEMETRY, ("telemetry_authorization_required", "naver_metrics_scope_limited")),
)
