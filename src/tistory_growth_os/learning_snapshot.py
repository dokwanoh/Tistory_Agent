from __future__ import annotations
from .site_config import blog_host

from dataclasses import dataclass
from datetime import date
from typing import assert_never

from .contracts.json_ast import (
    JsonArray, JsonBoolean, JsonNull, JsonNumber, JsonObject, JsonString, JsonValue,
)
from .domain.common import (
    Fields, array, boolean, date_value, fail, literal, strings, text,
)
from .domain.publishing_decode_support import integer


@dataclass(frozen=True, slots=True)
class ObservedRow:
    title: str
    views: int
    created_date: date


@dataclass(frozen=True, slots=True)
class Snapshot:
    day: date
    header_updated_at_display: str
    detail_cutoff: str | None
    interval_complete: bool
    truncated: bool
    rows: tuple[ObservedRow, ...]
    limitations: tuple[str, ...]


def decode_snapshot(value: JsonValue) -> Snapshot:
    fields = Fields.parse(value, "", (
        "scope", "source", "surface", "selected_calendar_day", "timezone",
        "header_updated_at_display", "detail_exact_update_time", "interval_complete",
        "table_truncated", "loading_completed", "detail_day_views",
        "aggregate_channels", "visible_rows", "limitations", "production_applied",
    ))
    _ = literal(fields, "scope", "private_read_only_ui_observation")
    _ = literal(fields, "source", "tistory")
    _ = literal(fields, "surface", f"https://{blog_host()}/manage/statistics/blog")
    _ = literal(fields, "timezone", "Asia/Seoul")
    if not boolean(fields, "loading_completed") or boolean(fields, "production_applied"):
        fail("", "observation", "expected loaded, unapplied observation")
    day = date_value(fields, "selected_calendar_day")
    total = integer(fields, "detail_day_views")
    channels = Fields.parse(fields.required("aggregate_channels"), "/aggregate_channels", (
        "search", "daum_search", "direct", "other_referral",
    ))
    for key in channels.keys:
        _ = integer(channels, key)
    rows: list[ObservedRow] = []
    titles: set[str] = set()
    for item in array(fields, "visible_rows", False):
        row = Fields.parse(item, "/visible_rows", ("title", "views", "created_date"))
        title = text(row, "title")
        created = date_value(row, "created_date")
        views = integer(row, "views")
        if title.strip() in titles or not title.strip() or created > day:
            fail("/visible_rows", "identity", "ambiguous title or invalid creation day")
        titles.add(title.strip())
        rows.append(ObservedRow(title, views, created))
    if sum(row.views for row in rows) > total:
        fail("/visible_rows", "total", "visible rows exceed detail total")
    cutoff = fields.required("detail_exact_update_time")
    match cutoff:
        case JsonNull():
            cutoff_text = None
        case JsonString(value=cutoff_text):
            if not cutoff_text.strip():
                fail("/detail_exact_update_time", "value", "empty cutoff")
        case JsonArray() | JsonBoolean() | JsonNumber() | JsonObject():
            fail("/detail_exact_update_time", "type", "expected display text or null")
        case _:
            assert_never(cutoff)
    return Snapshot(
        day, text(fields, "header_updated_at_display"), cutoff_text,
        boolean(fields, "interval_complete"), boolean(fields, "table_truncated"),
        tuple(rows), strings(fields, "limitations", False, r"[\s\S]+"),
    )
