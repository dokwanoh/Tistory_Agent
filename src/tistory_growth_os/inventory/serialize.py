from __future__ import annotations

from collections import Counter
from hashlib import sha256

from ..contracts.json_ast import (
    JsonArray,
    JsonBoolean,
    JsonMember,
    JsonNumber,
    JsonObject,
    JsonString,
)
from .models import (
    ClassifiedPost,
    FreshnessClass,
    IntentHint,
    PublicInventoryRequest,
    RiskClass,
)
from ..contracts.json_encode import encode_json_bytes


def inventory_json(
    request: PublicInventoryRequest,
    posts: tuple[ClassifiedPost, ...],
) -> JsonObject:
    freshness = Counter(post.freshness_class.value for post in posts)
    risk = Counter(post.risk_class.value for post in posts)
    intent = Counter(post.intent_hint.value for post in posts)
    result = JsonObject((
        JsonMember("schema_version", JsonString("1.0.0")),
        JsonMember("classification_version", JsonString("1.1.0")),
        JsonMember("blog_url", JsonString(request.blog_url)),
        JsonMember("checked_date", JsonString(request.checked_date.isoformat())),
        JsonMember("status", JsonString("pass")),
        JsonMember("post_count", JsonNumber(len(posts))),
        JsonMember("external_write_count", JsonNumber(0)),
        JsonMember("style_analysis_performed", JsonBoolean(False)),
        JsonMember("summary", JsonObject((
            JsonMember("freshness", _counts(
                freshness,
                tuple(item.value for item in FreshnessClass),
            )),
            JsonMember("risk", _counts(
                risk,
                tuple(item.value for item in RiskClass),
            )),
            JsonMember("intent_hint", _counts(
                intent,
                tuple(item.value for item in IntentHint),
            )),
        ))),
        JsonMember("posts", JsonArray(tuple(_post_json(post) for post in posts))),
    ))
    digest = sha256(encode_json_bytes(result)).hexdigest()
    return JsonObject(result.members + (
        JsonMember("inventory_id", JsonString(f"inventory_{digest}")),
    ))


def _counts(values: Counter[str], names: tuple[str, ...]) -> JsonObject:
    return JsonObject(tuple(
        JsonMember(name, JsonNumber(values[name]))
        for name in names
    ))


def _post_json(post: ClassifiedPost) -> JsonObject:
    snapshot = post.snapshot
    return JsonObject((
        JsonMember("canonical_url", JsonString(snapshot.canonical_url)),
        JsonMember("title", JsonString(snapshot.title)),
        JsonMember("published_at", JsonString(snapshot.published_at.isoformat())),
        JsonMember("modified_at", JsonString(snapshot.modified_at.isoformat())),
        JsonMember("category", JsonString(snapshot.category)),
        JsonMember("intent_hint", JsonString(post.intent_hint.value)),
        JsonMember("freshness_class", JsonString(post.freshness_class.value)),
        JsonMember("risk_class", JsonString(post.risk_class.value)),
        JsonMember("action_candidate", JsonString(post.action_candidate.value)),
        JsonMember("link_audit_status", JsonString("not_audited")),
        JsonMember("media_provenance_status", JsonString("unknown")),
        JsonMember("evidence_scope", JsonString("public_metadata_only")),
    ))
