from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final, Never
from urllib.parse import urlsplit

from .json_ast import (
    JsonArray,
    JsonBoolean,
    JsonNull,
    JsonNumber,
    JsonObject,
    JsonString,
    JsonValue,
)
from .json_decode import ContractIssue


KEYWORDS: Final = frozenset({
    "$schema",
    "$id",
    "$ref",
    "$defs",
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "minLength",
    "minItems",
    "pattern",
    "minimum",
    "maximum",
    "format",
    "oneOf",
})
JSON_TYPES: Final = frozenset({
    "null",
    "boolean",
    "integer",
    "number",
    "string",
    "array",
    "object",
})
FORMATS: Final = frozenset({"uri", "date", "date-time"})
RFC3339_DATE_TIME: Final = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)


@dataclass(frozen=True, slots=True)
class SchemaDefinitionError(Exception):
    issue: ContractIssue


def join_pointer(pointer: str, token: str) -> str:
    escaped = token.replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{escaped}"


def issue(pointer: str, keyword: str, message: str) -> ContractIssue:
    return ContractIssue(pointer, keyword, message)


def definition_error(pointer: str, keyword: str, message: str) -> Never:
    raise SchemaDefinitionError(issue(pointer, keyword, message))


def schema_object(value: JsonValue, pointer: str) -> JsonObject:
    match value:
        case JsonObject() as mapping:
            return mapping
        case _:
            definition_error(pointer, "schema", "schema must be an object")


def schema_array(value: JsonValue, pointer: str) -> JsonArray:
    match value:
        case JsonArray() as array:
            return array
        case _:
            definition_error(pointer, "schema", "keyword must be an array")


def required_string(value: JsonValue, pointer: str) -> str:
    match value:
        case JsonString(value=text):
            return text
        case _:
            definition_error(pointer, "schema", "keyword must be a string")


def optional_string(schema: JsonObject, name: str, pointer: str) -> str | None:
    value = schema.get(name)
    if value is None:
        return None
    return required_string(value, join_pointer(pointer, name))


def optional_integer(schema: JsonObject, name: str) -> int | None:
    value = schema.get(name)
    match value:
        case None:
            return None
        case JsonNumber(value=int() as integer):
            return integer
        case _:
            definition_error("", name, "keyword must be an integer")


def optional_number(schema: JsonObject, name: str) -> Decimal | None:
    value = schema.get(name)
    match value:
        case None:
            return None
        case JsonNumber(value=number):
            return Decimal(number)
        case _:
            definition_error("", name, "keyword must be a number")


def optional_boolean(schema: JsonObject, name: str) -> bool | None:
    value = schema.get(name)
    match value:
        case None:
            return None
        case JsonBoolean(value=boolean):
            return boolean
        case _:
            definition_error("", name, "keyword must be a boolean")


def optional_string_array(schema: JsonObject, name: str) -> tuple[str, ...]:
    value = schema.get(name)
    if value is None:
        return ()
    array = schema_array(value, f"/{name}")
    return tuple(required_string(item, f"/{name}") for item in array.items)


def matches_type(expected: JsonValue, instance: JsonValue) -> bool:
    match expected:
        case JsonString(value=name):
            return matches_named_type(name, instance)
        case JsonArray(items=items):
            return any(
                matches_named_type(required_string(item, "/type"), instance)
                for item in items
            )
        case _:
            definition_error("", "type", "type must be a string or string array")


def matches_named_type(name: str, instance: JsonValue) -> bool:
    match name, instance:
        case "null", JsonNull():
            return True
        case "boolean", JsonBoolean():
            return True
        case "integer", JsonNumber(value=int()):
            return True
        case "number", JsonNumber():
            return True
        case "string", JsonString():
            return True
        case "array", JsonArray():
            return True
        case "object", JsonObject():
            return True
        case _:
            return False


def format_matches(format_name: str, value: str) -> bool:
    try:
        match format_name:
            case "uri":
                parsed = urlsplit(value)
                has_authority = parsed.scheme not in {"http", "https"} or bool(parsed.netloc)
                return bool(parsed.scheme) and has_authority
            case "date":
                return date.fromisoformat(value).isoformat() == value
            case "date-time":
                if RFC3339_DATE_TIME.fullmatch(value) is None:
                    return False
                _ = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return True
            case _:
                definition_error("", "format", "unsupported format")
    except ValueError:
        return False


def resolve_reference(root: JsonObject, reference: str, pointer: str) -> JsonValue:
    current: JsonValue = root
    for raw_token in reference[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        match current:
            case JsonObject() as mapping:
                next_value = mapping.get(token)
                if next_value is None:
                    definition_error(pointer, "$ref", "local reference target does not exist")
                current = next_value
            case _:
                definition_error(pointer, "$ref", "local reference traverses a non-object")
    return current
