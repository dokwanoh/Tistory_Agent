from __future__ import annotations
from .site_config import blog_host

from dataclasses import dataclass
from datetime import date
from typing import TypedDict

from .contracts.json_ast import JsonValue
from .domain.common import Fields, array, date_value, fail, identifier, literal, text
from .domain.ids import PostId
from .learning_snapshot import Snapshot


@dataclass(frozen=True, slots=True)
class CatalogPost:
    post_id: PostId
    url: str
    title: str
    created_date: date
    evidence_ref: str


class LinkedRow(TypedDict):
    title: str
    post_id: str | None
    url: str | None
    evidence_ref: str | None
    join_status: str
    calendar_age_days: int


class CatalogMatch(TypedDict):
    catalog_sha256: str
    matched_rows: int
    rows: list[LinkedRow]
    same_calendar_window: bool
    same_creation_day: bool
    comparison_eligible: bool
    comparison_limits: list[str]


def decode_catalog(value: JsonValue) -> tuple[CatalogPost, ...]:
    fields = Fields.parse(value, "", ("schema_version", "posts"))
    _ = literal(fields, "schema_version", "publication-catalog-v1")
    posts: list[CatalogPost] = []
    seen: set[PostId] = set()
    for value in array(fields, "posts", False):
        row = Fields.parse(value, "/posts", ("post_id", "url", "title", "created_date", "evidence_ref"))
        post_id = PostId(identifier(row, "post_id", r"[1-9][0-9]*"))
        url = text(row, "url")
        if post_id in seen or url != f"https://{blog_host()}/{post_id}":
            fail("/posts", "identity", "unique ID and matching blog URL required")
        title = text(row, "title")
        evidence = text(row, "evidence_ref")
        if not title.strip() or not evidence.strip():
            fail("/posts", "value", "nonblank title and evidence required")
        seen.add(post_id)
        posts.append(CatalogPost(post_id, url, title, date_value(row, "created_date"), evidence))
    return tuple(posts)


def match_catalog(snapshot: Snapshot, posts: tuple[CatalogPost, ...], digest: str) -> CatalogMatch:
    rows: list[LinkedRow] = []
    matched = 0
    for row in snapshot.rows:
        candidates = [post for post in posts if post.title == row.title and post.created_date == row.created_date]
        post = candidates[0] if len(candidates) == 1 else None
        if post is not None:
            matched += 1
        rows.append(LinkedRow(
            title=row.title, post_id=str(post.post_id) if post else None,
            url=post.url if post else None, evidence_ref=post.evidence_ref if post else None,
            join_status="catalog_title_date_match" if post else ("ambiguous" if candidates else "unmatched"),
            calendar_age_days=(snapshot.day - row.created_date).days,
        ))
    limits = ["title_date_match_not_direct_stat_link", "calendar_age_not_exact_exposure_hours",
              "calendar_day_not_first_seven_days", "catalog_evidence_requires_trusted_input"]
    if matched != len(rows):
        limits.append("unresolved_identity")
    same_age = bool(rows) and len({row.created_date for row in snapshot.rows}) == 1
    if not same_age:
        limits.append("unequal_creation_days")
    if not snapshot.interval_complete:
        limits.append("partial_day")
    if snapshot.truncated:
        limits.append("truncated_table")
    if snapshot.detail_cutoff is None:
        limits.append("detail_cutoff_unknown")
    return CatalogMatch(
        catalog_sha256=digest, matched_rows=matched, rows=rows,
        same_calendar_window=bool(rows), same_creation_day=same_age,
        comparison_eligible=False, comparison_limits=limits,
    )
