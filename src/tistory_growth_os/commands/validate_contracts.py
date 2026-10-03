from __future__ import annotations

from pathlib import Path

from ..contracts.json_ast import JsonMember, JsonNumber, JsonObject, JsonString
from ..contracts.json_decode import JsonDecodeError, parse_json_file
from ..contracts.registry import ContractRegistry
from ..domain.content_catalog import CONTENT_ENTITY_CONTRACTS
from ..domain.content_request_decode import decode_offline_run_request
from ..domain.publishing_catalog import PUBLISHING_ENTITY_CONTRACTS


_VALID_FIXTURES = (
    "topic_supported.json",
    "topic_unsupported_claim.json",
    "topic_unverified_experience.json",
)
_NEGATIVE_FIXTURES = ("topic_malformed.json",)


def validate_contracts_json(root: Path) -> JsonObject:
    registry = ContractRegistry.load(root / "contracts")
    runtime = (*CONTENT_ENTITY_CONTRACTS, *PUBLISHING_ENTITY_CONTRACTS)
    for contract in runtime:
        entry = registry.get(contract.name)
        if entry.version != contract.version or entry.schema_id != contract.schema_id:
            raise ValueError(f"runtime contract registration mismatch: {contract.name}")
    fixtures = root / "tests" / "fixtures"
    for name in _VALID_FIXTURES:
        value = parse_json_file(fixtures / name)
        issues = registry.validate("offline-run-request", value)
        if issues:
            first = issues[0]
            raise ValueError(f"valid fixture failed at {first.pointer}: {first.message}")
        _ = decode_offline_run_request(value)
    for name in _NEGATIVE_FIXTURES:
        try:
            _ = parse_json_file(fixtures / name)
        except JsonDecodeError:
            continue
        raise ValueError(f"negative fixture unexpectedly parsed: {name}")
    return JsonObject((
        JsonMember("status", JsonString("pass")),
        JsonMember("contract_count", JsonNumber(len(registry.entries))),
        JsonMember("runtime_contract_count", JsonNumber(len(runtime))),
        JsonMember("valid_fixture_count", JsonNumber(len(_VALID_FIXTURES))),
        JsonMember(
            "expected_negative_fixture_count",
            JsonNumber(len(_NEGATIVE_FIXTURES)),
        ),
        JsonMember("external_write_count", JsonNumber(0)),
    ))
