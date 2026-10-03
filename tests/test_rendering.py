from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tistory_growth_os.contracts.json_decode import parse_json_file
from tistory_growth_os.contracts.json_encode import encode_json
from tistory_growth_os.domain.content_decode import decode_offline_run_request
from tistory_growth_os.domain.ids import QualityReportId
from tistory_growth_os.domain.publishing import QualityReport, ReportStatus
from tistory_growth_os.pipeline.brief import build_content_brief
from tistory_growth_os.pipeline.draft import build_article_draft
from tistory_growth_os.pipeline.evidence import parse_canonical_input_digest
from tistory_growth_os.rendering.html import (
    RenderDocument,
    RenderInvariantError,
    render_article_html,
)
from tistory_growth_os.rendering.metadata import build_review_metadata
from tistory_growth_os.rendering.rollback import build_local_rollback


ROOT = Path(__file__).resolve().parents[1]
BODY_HASH = f"sha256:{'b' * 64}"


class _DocumentParser(HTMLParser):  # noqa: MUTABLE_OK
    def __init__(self) -> None:
        super().__init__()
        self.starts: list[tuple[str, dict[str, str | None]]] = []
        self.text: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.starts.append((tag, dict(attrs)))

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def _render_document() -> RenderDocument:
    request = decode_offline_run_request(
        parse_json_file(ROOT / "tests/fixtures/topic_supported.json")
    )
    digest = parse_canonical_input_digest("1" * 64)
    brief = build_content_brief(request, digest)
    draft = build_article_draft(request, brief, digest)
    quality = QualityReport(
        report_id=QualityReportId("quality_aaaaaaaaaaaaaaaa"),
        draft_id=draft.draft_id,
        status=ReportStatus.PASS,
        score=Decimal(100),
        findings=(),
        claim_evidence_coverage=Decimal(1),
        evaluated_at=datetime.fromisoformat("2026-08-15T02:00:00+09:00"),
    )
    return RenderDocument(request, draft, quality, BODY_HASH)


def _parsed(html: str) -> _DocumentParser:
    parser = _DocumentParser()
    parser.feed(html)
    return parser


def test_supported_fixture_renders_semantic_editor_ready_korean_document() -> None:
    document = _render_document()
    rendered = render_article_html(document)
    parser = _parsed(rendered)
    tags = tuple(tag for tag, _ in parser.starts)
    page_text = " ".join(parser.text)

    assert rendered.startswith("<!doctype html>\n<html lang=\"ko\">")
    assert tags.count("h1") == 1
    assert all(tag in tags for tag in ("header", "nav", "main", "article", "aside", "footer"))
    assert "티스토리 글 발행 전 품질 체크리스트" in page_text
    assert "현재 지원 경로와 정책을 확인한다" in page_text
    assert "티스토리 Open API는 2024년 2월 말 종료되었다." in page_text
    assert "READY_FOR_APPROVAL" in page_text
    assert "외부 쓰기 0건" in page_text


def test_toc_headings_sources_and_media_are_accessible_and_ordered() -> None:
    document = _render_document()
    parser = _parsed(render_article_html(document))
    starts = parser.starts
    heading_ids = tuple(
        attrs["id"]
        for tag, attrs in starts
        if tag == "h2" and (attrs.get("id") or "").startswith("section-")
    )
    toc_hrefs = tuple(
        attrs["href"]
        for tag, attrs in starts
        if tag == "a" and attrs.get("class") == "toc-link"
    )
    images = tuple(attrs for tag, attrs in starts if tag == "img")
    source_links = tuple(
        attrs for tag, attrs in starts if tag == "a" and attrs.get("class") == "source-link"
    )

    assert toc_hrefs == tuple(f"#{heading_id}" for heading_id in heading_ids)
    assert len(images) == len(document.request.media) == 1
    assert all(attrs.get("alt") for attrs in images)
    assert all((attrs.get("src") or "").startswith("data:image/svg+xml,") for attrs in images)
    assert all((attrs.get("href") or "").startswith("https://") for attrs in source_links)
    assert any(tag == "nav" and attrs.get("aria-label") == "글 목차" for tag, attrs in starts)
    assert starts[0] == ("html", {"lang": "ko"})


def test_renderer_escapes_untrusted_text_and_rejects_unsafe_source_urls() -> None:
    document = _render_document()
    injected_topic = replace(document.request.topic, title='<script>alert("x")</script>')
    injected_media = replace(document.request.media[0], alt='대체문구" onerror="alert(1)')
    injected_request = replace(
        document.request,
        topic=injected_topic,
        media=(injected_media,),
    )
    injected_draft = replace(document.draft, title=injected_topic.title)
    rendered = render_article_html(replace(document, request=injected_request, draft=injected_draft))

    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in rendered
    assert 'onerror="alert(1)' not in rendered
    assert "대체문구&quot; onerror=&quot;alert(1)" in rendered

    unsafe_evidence = replace(document.request.evidence[0], url="javascript:alert(1)")
    unsafe_request = replace(
        document.request,
        evidence=(unsafe_evidence, *document.request.evidence[1:]),
    )
    with pytest.raises(RenderInvariantError) as caught:
        _ = render_article_html(replace(document, request=unsafe_request))
    assert caught.value.code == "UNSAFE_SOURCE_URL"


def test_document_is_self_contained_responsive_and_deterministic() -> None:
    document = _render_document()
    first = render_article_html(document).encode("utf-8")
    second = render_article_html(document).encode("utf-8")
    rendered = first.decode("utf-8")

    assert first == second
    assert "<script" not in rendered.lower()
    assert "@import" not in rendered.lower()
    assert "http://" not in rendered
    assert "https://" in rendered
    assert "--surface-paper: #fffdf9" in rendered
    assert "--space-4: 16px" in rendered
    assert "max-inline-size: 72ch" in rendered
    assert "font-size: 1rem" in rendered
    assert ":focus-visible" in rendered
    assert "@media (prefers-reduced-motion: reduce)" in rendered
    assert "@media print" in rendered
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in rendered
    assert "overflow-wrap: anywhere" in rendered


def test_mobile_korean_copy_keeps_words_while_machine_values_can_wrap() -> None:
    rendered = render_article_html(_render_document())

    assert "html { background: var(--surface-paper); color: var(--text-ink); }" in rendered
    assert "body { margin: 0;" in rendered
    assert "word-break: keep-all;" in rendered
    assert 'class="machine-value"' in rendered
    assert 'class="publisher">(Google Search Central)</span>' in rendered
    assert (
        ".machine-value { overflow-wrap: anywhere; word-break: break-all; "
        "font-family: inherit; }"
    ) in rendered
    assert ".publisher { white-space: nowrap; }" in rendered


def test_metadata_and_rollback_keep_approval_only_local_boundary() -> None:
    document = _render_document()
    metadata = encode_json(build_review_metadata(document))
    rollback = encode_json(build_local_rollback((
        "article.html",
        "metadata.json",
    )))

    assert '"title":"티스토리 글 발행 전 품질 체크리스트"' in metadata
    assert '"slug":"tistory-preflight"' in metadata
    assert '"description":"게시 전에 사실성, 정책, 접근성, 렌더링 결함을 어떻게 점검할 수 있는가?"' in metadata
    assert '"tags":["티스토리 운영","informational"]' in metadata
    assert '"category":{"owner_decision_id":"ODR-002","status":"OWNER_DECISION_REQUIRED","value":"UNKNOWN"}' in metadata
    assert '"visibility":{"owner_decision_id":"ODR-006","status":"OWNER_DECISION_REQUIRED","value":"UNKNOWN"}' in metadata
    assert '"publish_mode":"approval_required"' in metadata
    assert '"state":"ready_for_approval"' in metadata
    assert '"publication_status":"not_published"' in metadata
    assert f'"body_hash":"{BODY_HASH}"' in metadata
    assert '"claim_ids":["claim_tistory_api","claim_google_quality"]' in metadata
    assert '"source_ids":["src_tistory_api_notice","src_google_gen_ai"]' in metadata
    assert '"external_write_count":0' in metadata
    assert rollback == (
        '{"action":"discard_local_bundle","affected_paths":["article.html",'
        '"metadata.json"],"precondition":"not_published","remote_actions":[]}\n'
    )
