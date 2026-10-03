from __future__ import annotations

from decimal import Decimal
from unicodedata import normalize

from .json_ast import (
    JsonArray,
    JsonBoolean,
    JsonNull,
    JsonNumber,
    JsonObject,
    JsonString,
    JsonValue,
)


_STRING_ESCAPES = str.maketrans({
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
})


def encode_json(value: JsonValue) -> str:
    return f"{_encode(value)}\n"


def encode_json_bytes(value: JsonValue) -> bytes:
    return encode_json(value).encode("utf-8")


def _encode(value: JsonValue) -> str:
    match value:
        case JsonNull():
            return "null"
        case JsonBoolean(value=boolean):
            return "true" if boolean else "false"
        case JsonNumber(value=number):
            return _encode_number(number)
        case JsonString(value=text):
            return _encode_string(text)
        case JsonArray(items=items):
            return f"[{','.join(_encode(item) for item in items)}]"
        case JsonObject(members=members):
            ordered = sorted(members, key=lambda member: normalize("NFC", member.key))
            body = ",".join(
                f"{_encode_string(member.key)}:{_encode(member.value)}"
                for member in ordered
            )
            return f"{{{body}}}"


def _encode_string(value: str) -> str:
    normalized = normalize("NFC", value)
    escaped: list[str] = []
    for character in normalized:
        codepoint = ord(character)
        if codepoint < 0x20:
            replacement = character.translate(_STRING_ESCAPES)
            escaped.append(replacement if replacement != character else f"\\u{codepoint:04x}")
        else:
            escaped.append(character.translate(_STRING_ESCAPES))
    return f'"{"".join(escaped)}"'


def _encode_number(value: int | Decimal) -> str:
    match value:
        case int() as integer:
            return str(integer)
        case Decimal() as decimal:
            if not decimal.is_finite():
                raise ValueError("non-finite JSON number")
            rendered = format(decimal, "f")
            if "." in rendered:
                rendered = rendered.rstrip("0").rstrip(".")
            if rendered in {"-0", "0", ""}:
                return "0.0"
            return rendered if "." in rendered else f"{rendered}.0"
