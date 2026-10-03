from __future__ import annotations

import re
from decimal import Decimal

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
from .schema_support import (
    format_matches,
    issue,
    join_pointer,
    matches_type,
    optional_boolean,
    optional_integer,
    optional_number,
    optional_string,
    optional_string_array,
    resolve_reference,
    schema_array,
    schema_object,
)


def collect_issues(
    schema: JsonObject,
    instance: JsonValue,
    root: JsonObject,
) -> tuple[ContractIssue, ...]:
    issues: list[ContractIssue] = []
    _validate(schema, instance, "", root, issues)
    return tuple(sorted(issues))


def _validate(
    schema: JsonObject,
    instance: JsonValue,
    pointer: str,
    root: JsonObject,
    issues: list[ContractIssue],
) -> None:
    reference = optional_string(schema, "$ref", pointer)
    if reference is not None:
        target = resolve_reference(root, reference, pointer)
        _validate(schema_object(target, reference), instance, pointer, root, issues)
    expected = schema.get("type")
    if expected is not None and not matches_type(expected, instance):
        issues.append(issue(pointer, "type", "value does not match required type"))
        return
    const = schema.get("const")
    if const is not None and instance != const:
        issues.append(issue(pointer, "const", "value does not match const"))
    enum = schema.get("enum")
    if enum is not None:
        values = schema_array(enum, join_pointer(pointer, "enum")).items
        if instance not in values:
            issues.append(issue(pointer, "enum", "value is not in enum"))
    _validate_one_of(schema, instance, pointer, root, issues)
    match instance:
        case JsonString(value=text):
            _validate_string(schema, text, pointer, issues)
        case JsonNumber(value=number):
            _validate_number(schema, number, pointer, issues)
        case JsonArray(items=items):
            _validate_array(schema, items, pointer, root, issues)
        case JsonObject() as mapping:
            _validate_object(schema, mapping, pointer, root, issues)
        case JsonNull() | JsonBoolean():
            return


def _validate_one_of(
    schema: JsonObject,
    instance: JsonValue,
    pointer: str,
    root: JsonObject,
    issues: list[ContractIssue],
) -> None:
    one_of = schema.get("oneOf")
    if one_of is None:
        return
    matches = 0
    choices = schema_array(one_of, join_pointer(pointer, "oneOf"))
    for choice in choices.items:
        child_issues: list[ContractIssue] = []
        child_schema = schema_object(choice, pointer)
        _validate(child_schema, instance, pointer, root, child_issues)
        if not child_issues:
            matches += 1
    if matches != 1:
        issues.append(issue(pointer, "oneOf", "value must match exactly one schema"))


def _validate_string(
    schema: JsonObject,
    value: str,
    pointer: str,
    issues: list[ContractIssue],
) -> None:
    minimum = optional_integer(schema, "minLength")
    if minimum is not None and len(value) < minimum:
        issues.append(issue(pointer, "minLength", "string is shorter than minLength"))
    pattern = optional_string(schema, "pattern", pointer)
    if pattern is not None and re.search(pattern, value) is None:
        issues.append(issue(pointer, "pattern", "string does not match pattern"))
    format_name = optional_string(schema, "format", pointer)
    if format_name is not None and not format_matches(format_name, value):
        issues.append(issue(pointer, "format", f"string is not a valid {format_name}"))


def _validate_number(
    schema: JsonObject,
    value: int | Decimal,
    pointer: str,
    issues: list[ContractIssue],
) -> None:
    numeric = Decimal(value)
    minimum = optional_number(schema, "minimum")
    maximum = optional_number(schema, "maximum")
    if minimum is not None and numeric < minimum:
        issues.append(issue(pointer, "minimum", "number is below minimum"))
    if maximum is not None and numeric > maximum:
        issues.append(issue(pointer, "maximum", "number is above maximum"))


def _validate_array(
    schema: JsonObject,
    items: tuple[JsonValue, ...],
    pointer: str,
    root: JsonObject,
    issues: list[ContractIssue],
) -> None:
    minimum = optional_integer(schema, "minItems")
    if minimum is not None and len(items) < minimum:
        issues.append(issue(pointer, "minItems", "array has fewer items than minItems"))
    item_schema = schema.get("items")
    if item_schema is None:
        return
    parsed = schema_object(item_schema, join_pointer(pointer, "items"))
    for index, item in enumerate(items):
        _validate(parsed, item, join_pointer(pointer, str(index)), root, issues)


def _validate_object(
    schema: JsonObject,
    instance: JsonObject,
    pointer: str,
    root: JsonObject,
    issues: list[ContractIssue],
) -> None:
    properties_value = schema.get("properties")
    properties = (
        JsonObject(())
        if properties_value is None
        else schema_object(properties_value, pointer)
    )
    known = {member.key for member in properties.members}
    required = optional_string_array(schema, "required")
    present = {member.key for member in instance.members}
    for name in required:
        if name not in present:
            child_pointer = join_pointer(pointer, name)
            issues.append(issue(child_pointer, "required", "required property is missing"))
    additional = optional_boolean(schema, "additionalProperties")
    for member in instance.members:
        child_pointer = join_pointer(pointer, member.key)
        child_schema = properties.get(member.key)
        if child_schema is not None:
            parsed = schema_object(child_schema, child_pointer)
            _validate(parsed, member.value, child_pointer, root, issues)
        elif additional is False and member.key not in known:
            issues.append(
                issue(
                    child_pointer,
                    "additionalProperties",
                    "unknown property is not allowed",
                )
            )
