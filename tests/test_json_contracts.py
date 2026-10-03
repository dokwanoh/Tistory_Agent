from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from shutil import copytree

import pytest

import tistory_growth_os.contracts as contracts_api


ROOT = Path(__file__).resolve().parents[1]


def test_contract_boundary_public_seam_exists() -> None:
    assert hasattr(contracts_api, "parse_json"), "typed JSON boundary is not implemented"


def test_round_trip_korean_numbers_and_canonical_order() -> None:
    from tistory_growth_os.contracts.json_ast import JsonNumber, JsonObject, JsonString
    from tistory_growth_os.contracts.json_decode import parse_json
    from tistory_growth_os.contracts.json_encode import encode_json

    value = parse_json('{"한글":"Cafe\u0301","decimal":1.25,"integer":1}')
    assert isinstance(value, JsonObject)
    assert encode_json(value) == '{"decimal":1.25,"integer":1,"한글":"Café"}\n'
    members = {member.key: member.value for member in value.members}
    assert members["integer"] == JsonNumber(1)
    assert members["decimal"] == JsonNumber(Decimal("1.25"))
    assert members["한글"] == JsonString("Café")


@pytest.mark.parametrize(
    ("source", "detail", "pointer"),
    [
        ('{"a":1,"a":2}', "duplicate object key", "/a"),
        ('{"é":1,"e\\u0301":2}', "duplicate object key", "/é"),
        ('"\\uD800"', "unpaired high surrogate", ""),
        ('"\\uDC00"', "unpaired low surrogate", ""),
        ('"\\x"', "invalid escape", ""),
        ('"\x01"', "unescaped control character", ""),
        ("true false", "trailing content", ""),
        ("NaN", "unexpected token", ""),
        ("Infinity", "unexpected token", ""),
        ("١", "unexpected token", ""),
    ],
)
def test_invalid_json_fails_with_stable_issue(source: str, detail: str, pointer: str) -> None:
    from tistory_growth_os.contracts.json_decode import JsonDecodeError, parse_json

    with pytest.raises(JsonDecodeError) as raised:
        parse_json(source)
    assert raised.value.issue.code == "CONTRACT_INVALID"
    assert detail in raised.value.issue.message
    assert raised.value.issue.pointer == pointer
    assert raised.value.issue.line >= 1
    assert raised.value.issue.column >= 1


def test_valid_surrogate_pair_decodes() -> None:
    from tistory_growth_os.contracts.json_ast import JsonString
    from tistory_growth_os.contracts.json_decode import parse_json

    assert parse_json('"\\uD83D\\uDE00"') == JsonString("😀")


def test_registry_loads_catalog_and_validates_supported_fixture() -> None:
    from tistory_growth_os.contracts.registry import ContractRegistry

    registry = ContractRegistry.load(ROOT / "contracts")
    assert len(registry.entries) == 18
    issues = registry.validate_file("offline-run-request", ROOT / "tests/fixtures/topic_supported.json")
    assert issues == ()


def test_malformed_fixture_fails_closed() -> None:
    from tistory_growth_os.contracts.json_decode import JsonDecodeError
    from tistory_growth_os.contracts.registry import ContractRegistry

    registry = ContractRegistry.load(ROOT / "contracts")
    with pytest.raises(JsonDecodeError) as raised:
        registry.validate_file("offline-run-request", ROOT / "tests/fixtures/topic_malformed.json")
    assert raised.value.issue.code == "CONTRACT_INVALID"


def test_schema_subset_failures_are_deterministic() -> None:
    from tistory_growth_os.contracts.json_decode import parse_json
    from tistory_growth_os.contracts.schema import validate_schema

    schema = parse_json("".join((
        '{"$defs":{"identifier":{"type":"string","pattern":"^ok-[0-9]+$"}},',
        '"type":"object","additionalProperties":false,"properties":{',
        '"id":{"$ref":"#/$defs/identifier"},"uri":{"type":"string","format":"uri"},',
        '"date":{"type":"string","format":"date"},',
        '"when":{"type":"string","format":"date-time"},',
        '"choice":{"oneOf":[{"const":"a"},{"const":"b"}]},',
        '"count":{"type":"integer","minimum":1,"maximum":2},',
        '"label":{"type":"string","minLength":2},',
        '"items":{"type":"array","minItems":1,"items":{"enum":[1,2]}}},',
        '"required":["id","uri","date","when","choice","count","label","items"]}',
    )))
    instance = parse_json("".join((
        '{"extra":true,"id":"bad","uri":"relative","date":"2026-02-30",',
        '"when":"yesterday","choice":"c","count":3,"label":"x","items":[]}',
    )))
    issues = validate_schema(schema, instance)
    assert issues == tuple(sorted(issues, key=lambda issue: (issue.pointer, issue.keyword, issue.message)))
    assert {issue.keyword for issue in issues} >= {
        "additionalProperties", "format", "maximum", "minItems", "minLength", "oneOf", "pattern"
    }


@pytest.mark.parametrize(
    "schema_text",
    [
        '{"type":"string","unexpected":true}',
        '{"$ref":"https://example.com/schema.json"}',
    ],
)
def test_unsupported_schema_constructs_fail_closed(schema_text: str) -> None:
    from tistory_growth_os.contracts.json_decode import parse_json
    from tistory_growth_os.contracts.schema import SchemaDefinitionError, validate_schema

    with pytest.raises(SchemaDefinitionError) as raised:
        validate_schema(parse_json(schema_text), parse_json('"value"'))
    assert raised.value.issue.code == "CONTRACT_INVALID"


def test_integer_and_number_semantics() -> None:
    from tistory_growth_os.contracts.json_decode import parse_json
    from tistory_growth_os.contracts.json_encode import encode_json
    from tistory_growth_os.contracts.schema import validate_schema

    integer_schema = parse_json('{"type":"integer"}')
    number_schema = parse_json('{"type":"number"}')
    assert validate_schema(integer_schema, parse_json("1")) == ()
    assert validate_schema(integer_schema, parse_json("1.0")) != ()
    assert validate_schema(number_schema, parse_json("1.0")) == ()
    assert validate_schema(parse_json('{"type":"null"}'), parse_json("null")) == ()
    decimal = parse_json("1.0")
    assert parse_json(encode_json(decimal)) == decimal


def test_required_minimum_const_enum_and_items_failures() -> None:
    from tistory_growth_os.contracts.json_decode import parse_json
    from tistory_growth_os.contracts.schema import validate_schema

    schema = parse_json("".join((
        '{"type":"object","properties":{',
        '"fixed":{"const":"yes"},"level":{"enum":["low","high"]},',
        '"amount":{"type":"number","minimum":1},',
        '"list":{"type":"array","items":{"type":"string"}}},',
        '"required":["fixed","level","amount","list","missing"]}',
    )))
    issues = validate_schema(schema, parse_json('{"fixed":"no","level":"middle","amount":0,"list":[1]}'))
    assert {issue.keyword for issue in issues} == {"const", "enum", "minimum", "required", "type"}


@pytest.mark.parametrize("value", ["2026-08-15T00:00:00", "20260815T000000Z"])
def test_date_time_requires_full_rfc3339_with_timezone(value: str) -> None:
    from tistory_growth_os.contracts.json_ast import JsonString
    from tistory_growth_os.contracts.json_decode import parse_json
    from tistory_growth_os.contracts.schema import validate_schema

    schema = parse_json('{"type":"string","format":"date-time"}')
    issues = validate_schema(schema, JsonString(value))
    assert tuple(issue.keyword for issue in issues) == ("format",)
    assert validate_schema(schema, JsonString("2026-08-15T00:00:00+09:00")) == ()
    assert validate_schema(schema, JsonString("2026-08-15T00:00:00.123Z")) == ()


def test_registry_rejects_duplicate_schema_id(tmp_path: Path) -> None:
    from tistory_growth_os.contracts.registry import ContractRegistry
    from tistory_growth_os.contracts.schema import SchemaDefinitionError

    contracts_root = tmp_path / "contracts"
    _ = copytree(ROOT / "contracts", contracts_root)
    catalog = contracts_root / "catalog.json"
    changed = catalog.read_text(encoding="utf-8").replace(
        "urn:tistory-growth-os:schema:content-opportunity:1.0.0",
        "urn:tistory-growth-os:schema:topic-candidate:1.0.0",
        1,
    )
    catalog.write_text(changed, encoding="utf-8")
    with pytest.raises(SchemaDefinitionError) as raised:
        ContractRegistry.load(contracts_root)
    assert raised.value.issue.message == "duplicate schema identifier"


def test_registry_rejects_duplicate_schema_file(tmp_path: Path) -> None:
    from tistory_growth_os.contracts.registry import ContractRegistry
    from tistory_growth_os.contracts.schema import SchemaDefinitionError

    contracts_root = tmp_path / "contracts"
    _ = copytree(ROOT / "contracts", contracts_root)
    catalog = contracts_root / "catalog.json"
    changed = catalog.read_text(encoding="utf-8").replace(
        "schemas/content-opportunity.schema.json",
        "schemas/topic-candidate.schema.json",
        1,
    )
    catalog.write_text(changed, encoding="utf-8")
    with pytest.raises(SchemaDefinitionError) as raised:
        ContractRegistry.load(contracts_root)
    assert raised.value.issue.message == "duplicate schema file"
