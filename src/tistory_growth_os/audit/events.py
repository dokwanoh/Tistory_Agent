from __future__ import annotations

from ..contracts.json_ast import (
    JsonArray,
    JsonBoolean,
    JsonMember,
    JsonNumber,
    JsonObject,
    JsonString,
)
from ..domain.results import PipelineReady


def bundle_audit_json(result: PipelineReady, package_id: str) -> JsonObject:
    return JsonObject((
        JsonMember("schema_version", JsonString("1.0.0")),
        JsonMember("package_id", JsonString(package_id)),
        JsonMember("request_id", JsonString(result.request.request_id)),
        JsonMember(
            "state_history",
            JsonArray(tuple(JsonString(item.value) for item in result.state_history)),
        ),
        JsonMember("bundle_created", JsonBoolean(True)),
        JsonMember("external_write_count", JsonNumber(0)),
    ))


def audit_event_json(event: str, package_id: str, request_id: str) -> JsonObject:
    return JsonObject((
        JsonMember("event", JsonString(event)),
        JsonMember("package_id", JsonString(package_id)),
        JsonMember("request_id", JsonString(request_id)),
        JsonMember("external_write_count", JsonNumber(0)),
    ))
