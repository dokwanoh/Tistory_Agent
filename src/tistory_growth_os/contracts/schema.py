from __future__ import annotations

from .json_ast import JsonValue
from .json_decode import ContractIssue
from .schema_definition import check_definition
from .schema_support import SchemaDefinitionError, schema_object
from .schema_validation import collect_issues


def validate_schema(schema: JsonValue, instance: JsonValue) -> tuple[ContractIssue, ...]:
    root = schema_object(schema, "")
    check_definition(root, "")
    return collect_issues(root, instance, root)


def check_schema(schema: JsonValue) -> None:
    root = schema_object(schema, "")
    check_definition(root, "")


__all__ = ["SchemaDefinitionError", "check_schema", "validate_schema"]
