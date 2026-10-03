from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, TypeAlias


@dataclass(frozen=True, slots=True)
class JsonNull:
    pass


@dataclass(frozen=True, slots=True)
class JsonBoolean:
    value: bool


@dataclass(frozen=True, slots=True)
class JsonNumber:
    value: int | Decimal


@dataclass(frozen=True, slots=True)
class JsonString:
    value: str


@dataclass(frozen=True, slots=True)
class JsonMember:
    key: str
    value: JsonValue


@dataclass(frozen=True, slots=True)
class JsonArray:
    items: tuple[JsonValue, ...]


@dataclass(frozen=True, slots=True)
class JsonObject:
    members: tuple[JsonMember, ...]

    def get(self, key: str) -> JsonValue | None:
        for member in self.members:
            if member.key == key:
                return member.value
        return None


JsonValue: TypeAlias = JsonNull | JsonBoolean | JsonNumber | JsonString | JsonArray | JsonObject
JSON_NULL: Final = JsonNull()
