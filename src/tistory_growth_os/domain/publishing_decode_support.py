from __future__ import annotations

from decimal import Decimal

from tistory_growth_os.contracts.json_ast import (
    JsonArray,
    JsonBoolean,
    JsonNull,
    JsonNumber,
    JsonObject,
    JsonString,
)

from .common import Fields, fail, literal


def number(fields: Fields, key: str) -> Decimal:
    value = fields.required(key)
    match value:
        case JsonNumber(value=raw_number):
            result = Decimal(raw_number)
            if result < 0:
                fail(fields.child(key), "minimum", "number cannot be negative")
            return result
        case JsonNull() | JsonBoolean() | JsonString() | JsonArray() | JsonObject():
            fail(fields.child(key), "type", "expected number")


def signed_number(fields: Fields, key: str) -> Decimal:
    value = fields.required(key)
    match value:
        case JsonNumber(value=raw_number):
            return Decimal(raw_number)
        case JsonNull() | JsonBoolean() | JsonString() | JsonArray() | JsonObject():
            fail(fields.child(key), "type", "expected number")


def integer(fields: Fields, key: str) -> int:
    value = fields.required(key)
    match value:
        case JsonNumber(value=int() as result) if result >= 0:
            return result
        case JsonNumber():
            fail(fields.child(key), "type", "expected non-negative integer")
        case JsonNull() | JsonBoolean() | JsonString() | JsonArray() | JsonObject():
            fail(fields.child(key), "type", "expected integer")


def require_zero(fields: Fields, key: str) -> None:
    if integer(fields, key) != 0:
        fail(fields.child(key), "const", "expected zero external writes")


def require_version(fields: Fields) -> None:
    _ = literal(fields, "schema_version", "1.0.0")
