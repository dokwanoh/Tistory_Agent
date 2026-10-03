from __future__ import annotations

from ..contracts.json_ast import (
    JsonArray,
    JsonMember,
    JsonNumber,
    JsonObject,
    JsonString,
)

from .html import RenderDocument


def build_review_metadata(document: RenderDocument) -> JsonObject:
    return JsonObject((
        _string("schema_version", "1.0.0"),
        _string("title", document.draft.title),
        _string("slug", _slug(document.request.topic.topic_id)),
        _string("description", document.request.topic.core_question),
        JsonMember("tags", JsonArray((
            JsonString(document.request.topic.topic_cluster),
            JsonString(document.request.topic.search_intent.value),
        ))),
        JsonMember("category", _pending_value("ODR-002")),
        JsonMember("visibility", _pending_value("ODR-006")),
        _string("publish_mode", "approval_required"),
        _string("state", "ready_for_approval"),
        _string("publication_status", "not_published"),
        JsonMember("external_write_count", JsonNumber(0)),
        _string("quality_report_id", document.quality_report.report_id),
        _string("body_hash", document.body_hash),
        JsonMember("body_hash_inputs", JsonObject((
            _string("draft_id", document.draft.draft_id),
            _string("draft_version", document.draft.version),
            _string("article_title", document.draft.title),
            _string("content_encoding", "utf-8"),
        ))),
        JsonMember(
            "claim_ids",
            JsonArray(tuple(JsonString(item.claim_id) for item in document.request.claims)),
        ),
        JsonMember(
            "source_ids",
            JsonArray(tuple(JsonString(item.source_id) for item in document.request.evidence)),
        ),
    ))


def _string(key: str, value: str) -> JsonMember:
    return JsonMember(key, JsonString(value))


def _slug(topic_id: str) -> str:
    return topic_id.removeprefix("topic_").replace("_", "-")


def _pending_value(owner_decision_id: str) -> JsonObject:
    return JsonObject((
        _string("status", "OWNER_DECISION_REQUIRED"),
        _string("value", "UNKNOWN"),
        _string("owner_decision_id", owner_decision_id),
    ))
