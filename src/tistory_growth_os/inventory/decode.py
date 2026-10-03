from __future__ import annotations

from datetime import date, datetime
import re
from typing import Never, final, assert_never
from urllib.parse import urlsplit

from ..contracts.json_ast import JsonArray, JsonObject, JsonString, JsonValue, JsonNull, JsonBoolean, JsonNumber
from .models import BlogUrl, CanonicalUrl, PublicInventoryRequest, PublicPostSnapshot


@final
class InventoryInputError(ValueError):
    pass


def decode_public_inventory(value: JsonValue) -> PublicInventoryRequest:
    root = _object(value, "/")
    _exact_keys(root, {"schema_version", "blog_url", "checked_date", "posts"}, "/")
    if _string(root.get("schema_version"), "/schema_version") != "1.0.0":
        _fail("/schema_version", "unsupported schema version")
    blog_url = _blog_url(_string(root.get("blog_url"), "/blog_url"))
    checked_date = _date(_string(root.get("checked_date"), "/checked_date"))
    post_values = _array(root.get("posts"), "/posts")
    if not post_values.items:
        _fail("/posts", "at least one post is required")
    posts = tuple(
        _post(item, index, blog_url)
        for index, item in enumerate(post_values.items)
    )
    if any(post.modified_at.date() > checked_date for post in posts):
        _fail("/checked_date", "observation predates a post modification")
    urls = tuple(post.canonical_url for post in posts)
    if len(set(urls)) != len(urls):
        _fail("/posts", "canonical URLs must be unique")
    return PublicInventoryRequest(blog_url, checked_date, posts)


def _post(value: JsonValue, index: int, blog_url: BlogUrl) -> PublicPostSnapshot:
    pointer = f"/posts/{index}"
    post = _object(value, pointer)
    _exact_keys(
        post,
        {"canonical_url", "title", "published_at", "modified_at", "category"},
        pointer,
    )
    canonical = _canonical(
        _string(post.get("canonical_url"), f"{pointer}/canonical_url"),
        blog_url,
        f"{pointer}/canonical_url",
    )
    title = _nonempty(_string(post.get("title"), f"{pointer}/title"), f"{pointer}/title")
    published = _datetime(
        _string(post.get("published_at"), f"{pointer}/published_at"),
        f"{pointer}/published_at",
    )
    modified = _datetime(
        _string(post.get("modified_at"), f"{pointer}/modified_at"),
        f"{pointer}/modified_at",
    )
    if modified < published:
        _fail(f"{pointer}/modified_at", "modified time precedes published time")
    category = _nonempty(
        _string(post.get("category"), f"{pointer}/category"),
        f"{pointer}/category",
    )
    return PublicPostSnapshot(canonical, title, published, modified, category)


def _blog_url(value: str) -> BlogUrl:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
        or parsed.username is not None or parsed.password is not None
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        _fail("/blog_url", "blog URL must be an HTTPS origin")
    return BlogUrl(value.rstrip("/"))


def _canonical(value: str, blog_url: BlogUrl, pointer: str) -> CanonicalUrl:
    candidate = urlsplit(value)
    blog = urlsplit(blog_url)
    if (
        candidate.scheme != blog.scheme
        or candidate.netloc != blog.netloc
        or not candidate.path.startswith("/entry/")
        or candidate.query
        or candidate.fragment
    ):
        _fail(pointer, "canonical URL must be an entry on the audited blog")
    return CanonicalUrl(value)


def _date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _fail("/checked_date", "expected YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise InventoryInputError("/checked_date: invalid ISO date") from error


def _datetime(value: str, pointer: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        _fail(pointer, "expected RFC3339 date-time")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise InventoryInputError(f"{pointer}: invalid ISO date-time") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(pointer, "date-time requires an offset")
    return parsed


def _exact_keys(value: JsonObject, expected: set[str], pointer: str) -> None:
    if {member.key for member in value.members} != expected:
        _fail(pointer, "object has missing or unknown fields")


def _nonempty(value: str, pointer: str) -> str:
    normalized = value.strip()
    if not normalized:
        _fail(pointer, "value must not be empty")
    return normalized


def _object(value: JsonValue | None, pointer: str) -> JsonObject:
    match value:
        case JsonObject() as mapping:
            return mapping
        case JsonArray() | JsonString() | JsonNull() | JsonBoolean() | JsonNumber() | None:
            _fail(pointer, "expected object")
        case _:
            assert_never(value)


def _array(value: JsonValue | None, pointer: str) -> JsonArray:
    match value:
        case JsonArray() as array:
            return array
        case JsonObject() | JsonString() | JsonNull() | JsonBoolean() | JsonNumber() | None:
            _fail(pointer, "expected array")
        case _:
            assert_never(value)


def _string(value: JsonValue | None, pointer: str) -> str:
    match value:
        case JsonString(value=text):
            return text
        case JsonObject() | JsonArray() | JsonNull() | JsonBoolean() | JsonNumber() | None:
            _fail(pointer, "expected string")
        case _:
            assert_never(value)


def _fail(pointer: str, message: str) -> Never:
    raise InventoryInputError(f"{pointer}: {message}")
