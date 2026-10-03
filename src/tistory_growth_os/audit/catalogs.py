from __future__ import annotations

from pathlib import Path
from typing import Final

from tistory_growth_os.contracts.json_ast import JsonArray, JsonBoolean, JsonObject, JsonString, JsonValue
from tistory_growth_os.contracts.json_decode import JsonDecodeError, parse_json_file
from tistory_growth_os.contracts.registry import ContractRegistry
from tistory_growth_os.contracts.schema import SchemaDefinitionError

from .models import ContractsReport, OwnerDecisionsReport, PolicyEvidenceReport, TraceabilityReport


_ASIS_IDS: Final = tuple(f"ASIS-{index:03d}" for index in range(1, 13))
_TOBE_IDS: Final = tuple(f"TOBE-{index:03d}" for index in range(1, 13))
_CLAIM_IDS: Final = tuple(f"CL-{index:03d}" for index in range(1, 14))
_OWNER_IDS: Final = tuple(f"ODR-{index:03d}" for index in range(1, 8))
_ERASK: Final = (
    ("E", "Erase"),
    ("R", "Replace"),
    ("A", "Assist"),
    ("S", "reStruct"),
    ("K", "Keep"),
    ("C", "Create"),
)


def audit_traceability(root: Path) -> TraceabilityReport:
    path = root / "contracts/process-traceability.json"
    try:
        catalog = _as_object(parse_json_file(path))
    except (JsonDecodeError, OSError):
        return TraceabilityReport(_ASIS_IDS + _TOBE_IDS, (), ("catalog_invalid",))
    mappings = _as_array(catalog.get("mappings"))
    asis = tuple(_text(_field(item, "as_is_id")) for item in mappings.items)
    tobe = tuple(_text(_field(item, "to_be_id")) for item in mappings.items)
    missing = _missing(_ASIS_IDS, asis) + _missing(_TOBE_IDS, tobe)
    duplicates = _duplicates(asis) + _duplicates(tobe)
    issues = list(_vocabulary_issues(catalog))
    for item in mappings.items:
        mapping = _as_object(item)
        pair = (_text(mapping.get("primary_erask_code")), _text(mapping.get("primary_erask")))
        if pair not in _ERASK[:-1]:
            issues.append(f"invalid_mapping_erask:{_text(mapping.get('as_is_id'))}")
    created = _as_array(catalog.get("created_processes"))
    if not created.items or any(
        (_text(_field(item, "erask_code")), _text(_field(item, "erask"))) != _ERASK[-1]
        for item in created.items
    ):
        issues.append("create_records_invalid")
    return TraceabilityReport(tuple(sorted(missing)), tuple(sorted(duplicates)), tuple(sorted(issues)))


def audit_contracts(root: Path) -> ContractsReport:
    try:
        registry = ContractRegistry.load(root / "contracts")
    except (JsonDecodeError, SchemaDefinitionError, OSError) as error:
        return ContractsReport((f"catalog_invalid:{type(error).__name__}",))
    issues: list[str] = []
    if len(registry.entries) != 18:
        issues.append(f"schema_count:{len(registry.entries)}")
    names = tuple(entry.name for entry in registry.entries)
    identifiers = tuple(entry.schema_id for entry in registry.entries)
    files = tuple(entry.file for entry in registry.entries)
    for label, values in (("name", names), ("id", identifiers), ("file", files)):
        if len(set(values)) != len(values):
            issues.append(f"duplicate_schema_{label}")
    return ContractsReport(tuple(sorted(issues)))


def audit_policy_evidence(root: Path) -> PolicyEvidenceReport:
    try:
        catalog = _as_object(parse_json_file(root / "contracts/policy-evidence.json"))
    except (JsonDecodeError, OSError):
        return PolicyEvidenceReport(_CLAIM_IDS)
    claims = _as_array(catalog.get("claims"))
    valid: set[str] = set()
    for item in claims.items:
        claim = _as_object(item)
        claim_id = _text(claim.get("claim_id"))
        fields = ("source_url", "checked_at", "status", "control")
        complete = all(bool(_text(claim.get(field))) for field in fields)
        if claim_id == "CL-013":
            complete = complete and bool(_text(claim.get("temporal_qualifier")))
        if complete:
            valid.add(claim_id)
    missing = tuple(identifier for identifier in _CLAIM_IDS if identifier not in valid)
    return PolicyEvidenceReport(missing)


def audit_owner_decisions(root: Path) -> OwnerDecisionsReport:
    try:
        catalog = _as_object(parse_json_file(root / "contracts/owner-decisions.json"))
    except (JsonDecodeError, OSError):
        return OwnerDecisionsReport(("catalog_invalid",))
    decisions = _as_array(catalog.get("decisions"))
    issues: list[str] = []
    seen: list[str] = []
    for item in decisions.items:
        decision = _as_object(item)
        identifier = _text(decision.get("decision_id"))
        seen.append(identifier)
        accepted = (
            _text(decision.get("status")) == "OWNER_DECISION_REQUIRED"
            and _boolean(decision.get("offline_fixture_allowed"))
            and not _boolean(decision.get("external_write_allowed"))
        )
        if not accepted:
            issues.append(f"invalid:{identifier}")
    issues.extend(f"missing:{identifier}" for identifier in _OWNER_IDS if identifier not in seen)
    issues.extend(f"duplicate:{identifier}" for identifier in _duplicates(tuple(seen)))
    return OwnerDecisionsReport(tuple(sorted(issues)))


def _vocabulary_issues(catalog: JsonObject) -> tuple[str, ...]:
    values = _as_array(catalog.get("erask_vocabulary"))
    actual = tuple((_text(_field(item, "code")), _text(_field(item, "name"))) for item in values.items)
    return () if actual == _ERASK else ("erask_vocabulary_invalid",)


def _field(value: JsonValue, name: str) -> JsonValue | None:
    return _as_object(value).get(name)


def _as_object(value: JsonValue | None) -> JsonObject:
    match value:
        case JsonObject() as mapping:
            return mapping
        case _:
            return JsonObject(())


def _as_array(value: JsonValue | None) -> JsonArray:
    match value:
        case JsonArray() as array:
            return array
        case _:
            return JsonArray(())


def _text(value: JsonValue | None) -> str:
    match value:
        case JsonString(value=text):
            return text
        case _:
            return ""


def _boolean(value: JsonValue | None) -> bool:
    match value:
        case JsonBoolean(value=flag):
            return flag
        case _:
            return False


def _missing(expected: tuple[str, ...], actual: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(identifier for identifier in expected if identifier not in actual)


def _duplicates(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(identifier for identifier in set(values) if values.count(identifier) > 1))
