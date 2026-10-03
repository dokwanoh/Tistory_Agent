from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Never

from .json_ast import JsonArray, JsonObject, JsonString, JsonValue
from .json_decode import ContractIssue, parse_json_file
from .schema import SchemaDefinitionError, check_schema, validate_schema


@dataclass(frozen=True, slots=True)
class ContractEntry:
    name: str
    version: str
    file: str
    schema_id: str
    schema: JsonObject


@dataclass(frozen=True, slots=True)
class ContractRegistry:
    root: Path
    entries: tuple[ContractEntry, ...]

    @classmethod
    def load(cls, root: Path) -> ContractRegistry:
        catalog = _object(parse_json_file(root / "catalog.json"), "/")
        _require_exact_keys(catalog, {"schema_version", "schemas"}, "/")
        if _string(catalog.get("schema_version"), "/schema_version") != "1.0.0":
            _fail("/schema_version", "catalog", "unsupported catalog schema version")
        schemas = _array(catalog.get("schemas"), "/schemas")
        _reject_catalog_duplicates(schemas)
        entries = tuple(
            _load_entry(root, value, index)
            for index, value in enumerate(schemas.items)
        )
        names = {entry.name for entry in entries}
        if len(names) != len(entries):
            _fail("/schemas", "catalog", "duplicate contract name")
        return cls(root.resolve(), entries)

    def get(self, name: str) -> ContractEntry:
        for entry in self.entries:
            if entry.name == name:
                return entry
        _fail("/schemas", "catalog", f"unknown contract {name!r}")

    def validate(self, name: str, value: JsonValue) -> tuple[ContractIssue, ...]:
        return validate_schema(self.get(name).schema, value)

    def validate_file(self, name: str, path: Path) -> tuple[ContractIssue, ...]:
        return self.validate(name, parse_json_file(path))


def _load_entry(root: Path, value: JsonValue, index: int) -> ContractEntry:
    pointer = f"/schemas/{index}"
    mapping = _object(value, pointer)
    _require_exact_keys(mapping, {"name", "version", "file", "$id"}, pointer)
    name = _string(mapping.get("name"), f"{pointer}/name")
    version = _string(mapping.get("version"), f"{pointer}/version")
    relative = _string(mapping.get("file"), f"{pointer}/file")
    schema_id = _string(mapping.get("$id"), f"{pointer}/$id")
    path = (root / relative).resolve()
    try:
        _ = path.relative_to(root.resolve())
    except ValueError as error:
        _fail(f"{pointer}/file", "catalog", "schema path escapes contracts root", error)
    schema = _object(parse_json_file(path), f"{pointer}/file")
    check_schema(schema)
    actual_id = _string(schema.get("$id"), "/$id")
    if actual_id != schema_id:
        _fail(f"{pointer}/$id", "catalog", "catalog and schema identifiers differ")
    return ContractEntry(name, version, relative, schema_id, schema)


def _reject_catalog_duplicates(schemas: JsonArray) -> None:
    schema_ids: set[str] = set()
    files: set[str] = set()
    for index, value in enumerate(schemas.items):
        pointer = f"/schemas/{index}"
        mapping = _object(value, pointer)
        schema_id = _string(mapping.get("$id"), f"{pointer}/$id")
        relative = _string(mapping.get("file"), f"{pointer}/file")
        if schema_id in schema_ids:
            _fail(f"{pointer}/$id", "catalog", "duplicate schema identifier")
        if relative in files:
            _fail(f"{pointer}/file", "catalog", "duplicate schema file")
        schema_ids.add(schema_id)
        files.add(relative)


def _require_exact_keys(mapping: JsonObject, expected: set[str], pointer: str) -> None:
    actual = {member.key for member in mapping.members}
    if actual != expected:
        _fail(pointer, "catalog", "catalog object has missing or unknown fields")


def _object(value: JsonValue | None, pointer: str) -> JsonObject:
    match value:
        case JsonObject() as mapping:
            return mapping
        case _:
            _fail(pointer, "catalog", "expected object")


def _array(value: JsonValue | None, pointer: str) -> JsonArray:
    match value:
        case JsonArray() as array:
            return array
        case _:
            _fail(pointer, "catalog", "expected array")


def _string(value: JsonValue | None, pointer: str) -> str:
    match value:
        case JsonString(value=text):
            return text
        case _:
            _fail(pointer, "catalog", "expected string")


def _fail(pointer: str, keyword: str, message: str, cause: ValueError | None = None) -> Never:
    error = SchemaDefinitionError(ContractIssue(pointer, keyword, message))
    if cause is None:
        raise error
    raise error from cause
