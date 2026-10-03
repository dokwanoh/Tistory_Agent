from __future__ import annotations

import re

from .json_ast import JsonArray, JsonObject, JsonString, JsonValue
from .schema_support import (
    FORMATS,
    JSON_TYPES,
    KEYWORDS,
    definition_error,
    join_pointer,
    optional_boolean,
    optional_integer,
    optional_number,
    optional_string,
    required_string,
    schema_array,
    schema_object,
)


def check_definition(schema: JsonObject, pointer: str) -> None:
    for member in schema.members:
        if member.key not in KEYWORDS:
            definition_error(pointer, member.key, "unknown schema keyword")
    _check_string_keyword(schema, "$schema", pointer)
    _check_string_keyword(schema, "$id", pointer)
    type_value = schema.get("type")
    if type_value is not None:
        _check_type_value(type_value, join_pointer(pointer, "type"))
    for map_name in ("properties", "$defs"):
        map_value = schema.get(map_name)
        if map_value is not None:
            _check_schema_map(map_value, pointer, map_name)
    item_schema = schema.get("items")
    if item_schema is not None:
        child_pointer = join_pointer(pointer, "items")
        check_definition(schema_object(item_schema, child_pointer), child_pointer)
    _check_one_of(schema, pointer)
    _check_string_array(schema, "required", pointer)
    _check_array(schema, "enum", pointer)
    _check_boolean_keyword(schema, "additionalProperties")
    for integer_name in ("minLength", "minItems"):
        _check_nonnegative_integer(schema, integer_name, pointer)
    for number_name in ("minimum", "maximum"):
        _check_number_keyword(schema, number_name)
    _check_pattern(schema, pointer)
    format_name = optional_string(schema, "format", pointer)
    if format_name is not None and format_name not in FORMATS:
        definition_error(pointer, "format", "unsupported format")
    reference = optional_string(schema, "$ref", pointer)
    if reference is not None and not reference.startswith("#/"):
        definition_error(pointer, "$ref", "only local fragment references are supported")


def _check_schema_map(value: JsonValue, pointer: str, name: str) -> None:
    map_pointer = join_pointer(pointer, name)
    mapping = schema_object(value, map_pointer)
    for member in mapping.members:
        child_pointer = join_pointer(map_pointer, member.key)
        child = schema_object(member.value, child_pointer)
        check_definition(child, child_pointer)


def _check_one_of(schema: JsonObject, pointer: str) -> None:
    one_of = schema.get("oneOf")
    if one_of is None:
        return
    one_of_pointer = join_pointer(pointer, "oneOf")
    choices = schema_array(one_of, one_of_pointer)
    if not choices.items:
        definition_error(pointer, "oneOf", "oneOf must contain at least one schema")
    for index, choice in enumerate(choices.items):
        child_pointer = join_pointer(one_of_pointer, str(index))
        check_definition(schema_object(choice, child_pointer), child_pointer)


def _check_pattern(schema: JsonObject, pointer: str) -> None:
    pattern = optional_string(schema, "pattern", pointer)
    if pattern is None:
        return
    try:
        _ = re.compile(pattern)
    except re.error as error:
        definition_error(pointer, "pattern", f"invalid regular expression: {error.msg}")


def _check_type_value(value: JsonValue, pointer: str) -> None:
    match value:
        case JsonString(value=name):
            names = (name,)
        case JsonArray(items=items):
            names = tuple(required_string(item, pointer) for item in items)
        case _:
            definition_error(pointer, "type", "type must be a string or string array")
    if not names or any(name not in JSON_TYPES for name in names):
        definition_error(pointer, "type", "unsupported JSON type")


def _check_string_keyword(schema: JsonObject, name: str, pointer: str) -> None:
    _ = optional_string(schema, name, pointer)


def _check_string_array(schema: JsonObject, name: str, pointer: str) -> None:
    value = schema.get(name)
    if value is None:
        return
    keyword_pointer = join_pointer(pointer, name)
    array = schema_array(value, keyword_pointer)
    for item in array.items:
        _ = required_string(item, keyword_pointer)


def _check_array(schema: JsonObject, name: str, pointer: str) -> None:
    value = schema.get(name)
    if value is not None:
        _ = schema_array(value, join_pointer(pointer, name))


def _check_boolean_keyword(schema: JsonObject, name: str) -> None:
    if schema.get(name) is not None:
        _ = optional_boolean(schema, name)


def _check_nonnegative_integer(schema: JsonObject, name: str, pointer: str) -> None:
    value = optional_integer(schema, name)
    if value is not None and value < 0:
        definition_error(pointer, name, "keyword cannot be negative")


def _check_number_keyword(schema: JsonObject, name: str) -> None:
    if schema.get(name) is not None:
        _ = optional_number(schema, name)
