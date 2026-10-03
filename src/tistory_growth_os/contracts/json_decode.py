from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, Never, final
from unicodedata import normalize

from .json_ast import (
    JSON_NULL,
    JsonArray,
    JsonBoolean,
    JsonMember,
    JsonNumber,
    JsonObject,
    JsonString,
    JsonValue,
)


@dataclass(frozen=True, slots=True, order=True)
class ContractIssue:
    pointer: str
    keyword: str
    message: str
    code: str = "CONTRACT_INVALID"
    line: int = 1
    column: int = 1
    offset: int = 0


@dataclass(frozen=True, slots=True)
class JsonDecodeError(Exception):
    issue: ContractIssue


_ESCAPES: Final[dict[str, str]] = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


@final
class _Parser:
    __slots__ = ("source", "index")

    source: str
    index: int

    def __init__(self, source: str) -> None:
        self.source = source
        self.index = 0

    def parse(self) -> JsonValue:
        self._space()
        value = self._value("")
        self._space()
        if self.index != len(self.source):
            self._fail("trailing content", "")
        return value

    def _value(self, pointer: str) -> JsonValue:
        if self.index >= len(self.source):
            self._fail("unexpected end of input", pointer)
        current = self.source[self.index]
        match current:
            case '"':
                return JsonString(self._string(pointer))
            case "{":
                return self._object(pointer)
            case "[":
                return self._array(pointer)
            case "t":
                self._literal("true", pointer)
                return JsonBoolean(True)
            case "f":
                self._literal("false", pointer)
                return JsonBoolean(False)
            case "n":
                self._literal("null", pointer)
                return JSON_NULL
            case "-":
                return self._number(pointer)
            case digit if "0" <= digit <= "9":
                return self._number(pointer)
            case _:
                self._fail("unexpected token", pointer)

    def _object(self, pointer: str) -> JsonObject:
        self.index += 1
        self._space()
        members: list[JsonMember] = []
        keys: set[str] = set()
        if self._consume("}"):
            return JsonObject(())
        while True:
            if self.index >= len(self.source) or self.source[self.index] != '"':
                self._fail("object key must be a string", pointer)
            key = self._string(pointer)
            child_pointer = f"{pointer}/{_escape_pointer(key)}"
            canonical_key = normalize("NFC", key)
            if canonical_key in keys:
                self._fail("duplicate object key", child_pointer)
            keys.add(canonical_key)
            self._space()
            self._expect(":", child_pointer)
            self._space()
            members.append(JsonMember(key, self._value(child_pointer)))
            self._space()
            if self._consume("}"):
                return JsonObject(tuple(members))
            self._expect(",", pointer)
            self._space()

    def _array(self, pointer: str) -> JsonArray:
        self.index += 1
        self._space()
        items: list[JsonValue] = []
        if self._consume("]"):
            return JsonArray(())
        while True:
            items.append(self._value(f"{pointer}/{len(items)}"))
            self._space()
            if self._consume("]"):
                return JsonArray(tuple(items))
            self._expect(",", pointer)
            self._space()

    def _string(self, pointer: str) -> str:
        self.index += 1
        parts: list[str] = []
        while self.index < len(self.source):
            current = self.source[self.index]
            self.index += 1
            if current == '"':
                return "".join(parts)
            if current == "\\":
                parts.append(self._escape(pointer))
            elif ord(current) < 0x20:
                self._fail("unescaped control character", pointer, self.index - 1)
            elif 0xD800 <= ord(current) <= 0xDFFF:
                self._fail("unpaired surrogate", pointer, self.index - 1)
            else:
                parts.append(current)
        self._fail("unterminated string", pointer)

    def _escape(self, pointer: str) -> str:
        if self.index >= len(self.source):
            self._fail("unterminated escape", pointer)
        marker = self.source[self.index]
        self.index += 1
        if marker == "u":
            return self._unicode_escape(pointer)
        if marker in _ESCAPES:
            return _ESCAPES[marker]
        self._fail("invalid escape", pointer, self.index - 1)

    def _unicode_escape(self, pointer: str) -> str:
        first = self._hex_quad(pointer)
        if 0xDC00 <= first <= 0xDFFF:
            self._fail("unpaired low surrogate", pointer, self.index - 4)
        if 0xD800 <= first <= 0xDBFF:
            if self.source[self.index : self.index + 2] != "\\u":
                self._fail("unpaired high surrogate", pointer, self.index - 4)
            self.index += 2
            second = self._hex_quad(pointer)
            if not 0xDC00 <= second <= 0xDFFF:
                self._fail("unpaired high surrogate", pointer, self.index - 10)
            return chr(0x10000 + ((first - 0xD800) << 10) + second - 0xDC00)
        return chr(first)

    def _hex_quad(self, pointer: str) -> int:
        end = self.index + 4
        digits = self.source[self.index : end]
        invalid_digit = any(
            character not in "0123456789abcdefABCDEF" for character in digits
        )
        if len(digits) != 4 or invalid_digit:
            self._fail("invalid unicode escape", pointer)
        self.index = end
        return int(digits, 16)

    def _number(self, pointer: str) -> JsonNumber:
        start = self.index
        _ = self._consume("-")
        if self._consume("0"):
            if self.index < len(self.source) and "0" <= self.source[self.index] <= "9":
                self._fail("leading zero in number", pointer)
        else:
            self._digits(pointer)
        decimal = False
        if self._consume("."):
            decimal = True
            self._digits(pointer)
        if self.index < len(self.source) and self.source[self.index] in "eE":
            decimal = True
            self.index += 1
            if self.index < len(self.source) and self.source[self.index] in "+-":
                self.index += 1
            self._digits(pointer)
        token = self.source[start : self.index]
        try:
            return JsonNumber(Decimal(token) if decimal else int(token))
        except (InvalidOperation, ValueError):
            self._fail("invalid number", pointer, start)

    def _digits(self, pointer: str) -> None:
        start = self.index
        while self.index < len(self.source) and "0" <= self.source[self.index] <= "9":
            self.index += 1
        if self.index == start:
            self._fail("number requires a digit", pointer)

    def _literal(self, literal: str, pointer: str) -> None:
        if not self.source.startswith(literal, self.index):
            self._fail("unexpected token", pointer)
        self.index += len(literal)

    def _expect(self, token: str, pointer: str) -> None:
        if not self._consume(token):
            self._fail(f"expected {token!r}", pointer)

    def _consume(self, token: str) -> bool:
        if self.source.startswith(token, self.index):
            self.index += len(token)
            return True
        return False

    def _space(self) -> None:
        while self.index < len(self.source) and self.source[self.index] in " \t\r\n":
            self.index += 1

    def _fail(self, message: str, pointer: str, offset: int | None = None) -> Never:
        location = self.index if offset is None else offset
        prefix = self.source[:location]
        line = prefix.count("\n") + 1
        last_break = prefix.rfind("\n")
        column = location + 1 if last_break < 0 else location - last_break
        issue = ContractIssue(
            pointer,
            "json",
            message,
            line=line,
            column=column,
            offset=location,
        )
        raise JsonDecodeError(issue)


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def parse_json(source: str | bytes) -> JsonValue:
    match source:
        case bytes() as binary:
            try:
                text = binary.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                issue = ContractIssue(
                    "",
                    "json",
                    "input is not valid UTF-8",
                    offset=error.start,
                    column=error.start + 1,
                )
                raise JsonDecodeError(issue) from error
        case str() as string:
            text = string
    return _Parser(text).parse()


def parse_json_file(path: Path) -> JsonValue:
    return parse_json(path.read_bytes())
