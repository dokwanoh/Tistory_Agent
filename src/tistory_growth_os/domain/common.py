from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum, unique
import re
from typing import Never, TypeVar

from tistory_growth_os.contracts.json_ast import (
    JsonArray,
    JsonBoolean,
    JsonNull,
    JsonNumber,
    JsonObject,
    JsonString,
    JsonValue,
)
from tistory_growth_os.contracts.json_decode import ContractIssue, JsonDecodeError


@unique
class SearchIntent(StrEnum):
    INFORMATIONAL = "informational"
    NAVIGATIONAL = "navigational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"


@unique
class TopicStatus(StrEnum):
    CAPTURED = "captured"
    SCREENED = "screened"
    REJECTED = "rejected"


@unique
class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@unique
class UnknownScore(StrEnum):
    UNKNOWN = "unknown"


@unique
class SourceType(StrEnum):
    OFFICIAL = "official"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    OWNER = "owner"


@unique
class LicenseStatus(StrEnum):
    LINK_AND_PARAPHRASE = "link_and_paraphrase"
    QUOTED_WITH_LIMIT = "quoted_with_limit"
    OWNER_PROVIDED = "owner_provided"
    REVIEW_REQUIRED = "review_required"


@unique
class ClaimKind(StrEnum):
    FACTUAL = "factual"
    FIRST_PERSON_EXPERIENCE = "first_person_experience"
    DISCLOSURE = "disclosure"
    OPINION = "opinion"


@unique
class SupportState(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    OWNER_VERIFICATION_REQUIRED = "owner_verification_required"
    DISPUTED = "disputed"


@unique
class OwnerEvidenceStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    VERIFIED = "verified"
    REQUIRED = "required"


@unique
class QualityStatus(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    PASS = "pass"
    BLOCKED = "blocked"


@unique
class DisclosureBasis(StrEnum):
    NONE = "none"
    ADVERTISING = "advertising"
    AFFILIATE = "affiliate"
    SPONSORSHIP = "sponsorship"
    AI_VIRTUAL_PERSON = "ai_virtual_person"


@unique
class MediaKind(StrEnum):
    PLACEHOLDER = "placeholder"


@unique
class MediaLicenseStatus(StrEnum):
    GENERATED_PLACEHOLDER = "generated_placeholder"


@dataclass(frozen=True, slots=True)
class Provenance:
    checked_at: datetime
    as_of: date


EnumValue = TypeVar("EnumValue", bound=StrEnum)


@dataclass(frozen=True, slots=True)
class Fields:
    value: JsonObject
    pointer: str
    keys: tuple[str, ...]

    @classmethod
    def parse(cls, value: JsonValue, pointer: str, keys: tuple[str, ...]) -> Fields:
        item = as_object(value, pointer)
        present = tuple(member.key for member in item.members)
        for key in keys:
            if key not in present:
                fail(f"{pointer}/{key}", "required", "required field is missing")
        for key in present:
            if key not in keys:
                fail(f"{pointer}/{key}", "additionalProperties", "unknown field")
        return cls(item, pointer, keys)

    def required(self, key: str) -> JsonValue:
        value = self.value.get(key)
        if value is None:
            fail(f"{self.pointer}/{key}", "required", "required field is missing")
        return value

    def child(self, key: str) -> str:
        return f"{self.pointer}/{key}"


def as_object(value: JsonValue, pointer: str) -> JsonObject:
    match value:
        case JsonObject():
            return value
        case JsonNull() | JsonBoolean() | JsonNumber() | JsonString() | JsonArray():
            fail(pointer, "type", "expected object")


def array(fields: Fields, key: str, populated: bool) -> tuple[JsonValue, ...]:
    value = fields.required(key)
    match value:
        case JsonArray(items=items):
            if populated and not items:
                fail(fields.child(key), "minItems", "expected at least one item")
            return items
        case JsonNull() | JsonBoolean() | JsonNumber() | JsonString() | JsonObject():
            fail(fields.child(key), "type", "expected array")


def text(fields: Fields, key: str) -> str:
    value = fields.required(key)
    match value:
        case JsonString(value=result) if result:
            return result
        case JsonString():
            fail(fields.child(key), "minLength", "expected non-empty string")
        case JsonNull() | JsonBoolean() | JsonNumber() | JsonArray() | JsonObject():
            fail(fields.child(key), "type", "expected string")


def literal(fields: Fields, key: str, expected: str) -> str:
    value = text(fields, key)
    if value != expected:
        fail(fields.child(key), "const", f"expected {expected!r}")
    return value


def identifier(fields: Fields, key: str, pattern: str) -> str:
    value = text(fields, key)
    if re.fullmatch(pattern, value) is None:
        fail(fields.child(key), "pattern", "value does not match contract pattern")
    return value


def enum_value(fields: Fields, key: str, enum_type: type[EnumValue]) -> EnumValue:
    value = text(fields, key)
    try:
        return enum_type(value)
    except ValueError:
        fail(fields.child(key), "enum", "value is outside the allowed set")


def date_value(fields: Fields, key: str) -> date:
    value = text(fields, key)
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        fail(fields.child(key), "format", "expected RFC 3339 date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        fail(fields.child(key), "format", "expected RFC 3339 date")


def datetime_value(fields: Fields, key: str) -> datetime:
    value = text(fields, key)
    pattern = (
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})"
    )
    if re.fullmatch(pattern, value) is None:
        fail(fields.child(key), "format", "expected RFC 3339 date-time")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(fields.child(key), "format", "expected RFC 3339 date-time")
    if result.tzinfo is None:
        fail(fields.child(key), "format", "date-time requires an offset")
    return result


def boolean(fields: Fields, key: str) -> bool:
    value = fields.required(key)
    match value:
        case JsonBoolean(value=result):
            return result
        case JsonNull() | JsonNumber() | JsonString() | JsonArray() | JsonObject():
            fail(fields.child(key), "type", "expected boolean")


def strings(fields: Fields, key: str, populated: bool, pattern: str) -> tuple[str, ...]:
    items = array(fields, key, populated)
    result: list[str] = []
    for index, item in enumerate(items):
        match item:
            case JsonString(value=value) if re.fullmatch(pattern, value) is not None:
                result.append(value)
            case JsonString():
                fail(f"{fields.child(key)}/{index}", "pattern", "value does not match contract pattern")
            case JsonNull() | JsonBoolean() | JsonNumber() | JsonArray() | JsonObject():
                fail(f"{fields.child(key)}/{index}", "type", "expected string")
    if len(result) != len(set(result)):
        fail(fields.child(key), "uniqueItems", "duplicate values are not allowed")
    return tuple(result)


def score(fields: Fields, key: str) -> Decimal | UnknownScore:
    value = fields.required(key)
    match value:
        case JsonString(value="unknown"):
            return UnknownScore.UNKNOWN
        case JsonNumber(value=number):
            result = Decimal(number)
            if result < 0 or result > 100:
                fail(fields.child(key), "range", "score must be between 0 and 100")
            return result
        case JsonString():
            fail(fields.child(key), "const", "expected 'unknown'")
        case JsonNull() | JsonBoolean() | JsonArray() | JsonObject():
            fail(fields.child(key), "type", "expected number or 'unknown'")


def fail(pointer: str, keyword: str, message: str) -> Never:
    raise JsonDecodeError(ContractIssue(pointer=pointer, keyword=keyword, message=message))
