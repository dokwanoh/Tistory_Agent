from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
from typing import Never, final

from tistory_growth_os.contracts.json_ast import (
    JsonArray,
    JsonBoolean,
    JsonNull,
    JsonNumber,
    JsonObject,
    JsonString,
    JsonValue,
)
from tistory_growth_os.contracts.json_decode import parse_json_file
from tistory_growth_os.domain.ids import OwnerDecisionId


@final
class PolicyCatalogError(ValueError):
    __slots__ = ("path", "message")

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"POLICY_EVIDENCE_REQUIRED at {path}: {message}")


@dataclass(frozen=True, slots=True)
class PolicyClaim:
    claim_id: str
    control: str
    source_url: str
    checked_at: str

    @property
    def evidence_is_complete(self) -> bool:
        if not self.source_url.startswith(("https://", "workspace://")):
            return False
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.checked_at) is None:
            return False
        try:
            _ = date.fromisoformat(self.checked_at)
        except ValueError:
            return False
        return True


@dataclass(frozen=True, slots=True)
class OwnerDecision:
    decision_id: OwnerDecisionId
    offline_fixture_allowed: bool
    external_write_allowed: bool


@dataclass(frozen=True, slots=True)
class PolicyCatalog:
    claims: tuple[PolicyClaim, ...]
    prohibited_ad_formats: tuple[str, ...]

    def claim_for_control(self, control: str) -> PolicyClaim:
        for claim in self.claims:
            if claim.control == control:
                return claim
        raise PolicyCatalogError("/claims", f"missing policy control {control}")


@dataclass(frozen=True, slots=True)
class OwnerDecisionCatalog:
    decisions: tuple[OwnerDecision, ...]

    def decision(self, decision_id: OwnerDecisionId) -> OwnerDecision:
        for decision in self.decisions:
            if decision.decision_id == decision_id:
                return decision
        raise PolicyCatalogError("/decisions", f"missing owner decision {decision_id}")


@dataclass(frozen=True, slots=True)
class PolicyCatalogs:
    policy: PolicyCatalog
    owner_decisions: OwnerDecisionCatalog


def load_policy_catalogs(root: Path) -> PolicyCatalogs:
    contracts = root / "contracts"
    policy = _policy_catalog(parse_json_file(contracts / "policy-evidence.json"))
    owners = _owner_catalog(parse_json_file(contracts / "owner-decisions.json"))
    return PolicyCatalogs(policy, owners)


def _policy_catalog(value: JsonValue) -> PolicyCatalog:
    source = _mapping(value, "")
    claims = _array(source.get("claims"), "/claims")
    parsed = tuple(_policy_claim(item, index) for index, item in enumerate(claims.items))
    formats = tuple(
        _required_string(item, f"/prohibited_ad_formats/{index}")
        for index, item in enumerate(
            _array(source.get("prohibited_ad_formats"), "/prohibited_ad_formats").items
        )
    )
    if not parsed:
        _fail("/claims", "at least one policy claim is required")
    if len({claim.control for claim in parsed}) != len(parsed):
        _fail("/claims", "policy controls must be unique")
    return PolicyCatalog(parsed, formats)


def _owner_catalog(value: JsonValue) -> OwnerDecisionCatalog:
    source = _mapping(value, "")
    decisions = _array(source.get("decisions"), "/decisions")
    parsed = tuple(_owner_decision(item, index) for index, item in enumerate(decisions.items))
    if len({decision.decision_id for decision in parsed}) != len(parsed):
        _fail("/decisions", "owner decision identifiers must be unique")
    return OwnerDecisionCatalog(parsed)


def _policy_claim(value: JsonValue, index: int) -> PolicyClaim:
    path = f"/claims/{index}"
    mapping = _mapping(value, path)
    return PolicyClaim(
        claim_id=_required_string(mapping.get("claim_id"), f"{path}/claim_id"),
        control=_required_string(mapping.get("control"), f"{path}/control"),
        source_url=_optional_string(mapping.get("source_url"), f"{path}/source_url"),
        checked_at=_optional_string(mapping.get("checked_at"), f"{path}/checked_at"),
    )


def _owner_decision(value: JsonValue, index: int) -> OwnerDecision:
    path = f"/decisions/{index}"
    mapping = _mapping(value, path)
    return OwnerDecision(
        decision_id=OwnerDecisionId(
            _required_string(mapping.get("decision_id"), f"{path}/decision_id")
        ),
        offline_fixture_allowed=_boolean(
            mapping.get("offline_fixture_allowed"), f"{path}/offline_fixture_allowed"
        ),
        external_write_allowed=_boolean(
            mapping.get("external_write_allowed"), f"{path}/external_write_allowed"
        ),
    )


def _mapping(value: JsonValue | None, path: str) -> JsonObject:
    match value:
        case JsonObject() as result:
            return result
        case JsonArray() | JsonBoolean() | JsonNull() | JsonNumber() | JsonString() | None:
            _fail(path, "expected object")


def _array(value: JsonValue | None, path: str) -> JsonArray:
    match value:
        case JsonArray() as result:
            return result
        case JsonBoolean() | JsonNull() | JsonNumber() | JsonObject() | JsonString() | None:
            _fail(path, "expected array")


def _required_string(value: JsonValue | None, path: str) -> str:
    text = _optional_string(value, path)
    if not text:
        _fail(path, "expected non-empty string")
    return text


def _optional_string(value: JsonValue | None, path: str) -> str:
    match value:
        case JsonString(value=text):
            return text
        case JsonArray() | JsonBoolean() | JsonNull() | JsonNumber() | JsonObject() | None:
            _fail(path, "expected string")


def _boolean(value: JsonValue | None, path: str) -> bool:
    match value:
        case JsonBoolean(value=result):
            return result
        case JsonArray() | JsonNull() | JsonNumber() | JsonObject() | JsonString() | None:
            _fail(path, "expected boolean")


def _fail(path: str, message: str) -> Never:
    raise PolicyCatalogError(path, message)
