from __future__ import annotations

from dataclasses import dataclass
from html import escape
import re
from typing import Final, final
from urllib.parse import urlsplit

from tistory_growth_os.domain.content import (
    ArticleDraft,
    DraftSection,
    MediaPlaceholder,
    OfflineRunRequest,
    SourceEvidence,
)
from tistory_growth_os.domain.ids import SourceId
from tistory_growth_os.domain.publishing import QualityReport, ReportStatus


_BODY_HASH: Final = re.compile(r"sha256:[a-f0-9]{64}")
_PLACEHOLDER_SVG: Final = (
    "data:image/svg+xml,%3Csvg%20xmlns='http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg'%20"
    "viewBox='0%200%201200%20675'%3E%3Crect%20width='1200'%20height='675'%20"
    "fill='%23f6f2eb'%2F%3E%3Cpath%20d='M80%20595L380%20310l180%20170%20230-220%20"
    "330%20335'%20fill='none'%20stroke='%23d8d1c6'%20stroke-width='24'%2F%3E"
    "%3Ccircle%20cx='900'%20cy='180'%20r='72'%20fill='%23d8d1c6'%2F%3E%3C%2Fsvg%3E"
)


@final
class RenderInvariantError(ValueError):
    __slots__ = ("code", "path", "message")

    code: str
    path: str
    message: str

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True, slots=True)
class RenderDocument:
    request: OfflineRunRequest
    draft: ArticleDraft
    quality_report: QualityReport
    body_hash: str

    def __post_init__(self) -> None:
        if self.draft.title != self.request.topic.title:
            raise RenderInvariantError("CONTRACT_INVALID", "/draft/title", "title differs from request")
        if self.quality_report.draft_id != self.draft.draft_id:
            raise RenderInvariantError("CONTRACT_INVALID", "/quality_report/draft_id", "draft identity differs")
        if self.quality_report.status is not ReportStatus.PASS:
            raise RenderInvariantError("QUALITY_GATE_REQUIRED", "/quality_report/status", "quality gate must pass")
        if _BODY_HASH.fullmatch(self.body_hash) is None:
            raise RenderInvariantError("CONTRACT_INVALID", "/body_hash", "expected prefixed SHA-256")


def render_article_html(document: RenderDocument) -> str:
    sources = {item.source_id: item for item in document.request.evidence}
    toc = "\n".join(
        f'<li><a class="toc-link" href="#section-{index + 1}">{escape(section.heading)}</a></li>'
        for index, section in enumerate(document.draft.sections)
    )
    sections = "\n".join(
        _render_section(index, section, sources)
        for index, section in enumerate(document.draft.sections)
    )
    media = "\n".join(_render_media(item) for item in document.request.media)
    media_region = f'''    <section class="media-region" aria-labelledby="media-title">
      <h2 id="media-title">이미지 자리표시자</h2>
      {media}
    </section>''' if document.request.media else ""
    source_list = "\n".join(_render_source_list_item(item) for item in document.request.evidence)
    title = escape(document.draft.title)
    summary = escape(document.draft.summary)
    description = escape(document.request.topic.core_question, quote=True)
    report_id = escape(document.quality_report.report_id)
    body_hash = escape(document.body_hash)
    as_of = escape(document.draft.as_of.isoformat())
    return f'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{description}">
  <title>{title}</title>
  <style>{_STYLES}</style>
</head>
<body>
  <a class="skip-link" href="#main-content">본문으로 건너뛰기</a>
  <header class="page-header reading-column">
    <p class="eyebrow">TISTORY GROWTH OS · 오프라인 검토본</p>
    <aside class="readiness" aria-label="게시 준비 상태">
      <strong>READY_FOR_APPROVAL</strong>
      <span>승인 필요 · 외부 쓰기 0건</span>
      <span>품질 보고서 <code class="machine-value">{report_id}</code> · 본문 해시 <code class="machine-value">{body_hash}</code></span>
    </aside>
    <h1>{title}</h1>
    <dl class="metadata"><div><dt>기준일</dt><dd>{as_of}</dd></div><div><dt>언어</dt><dd>ko-KR</dd></div></dl>
  </header>
  <nav class="toc reading-column" aria-label="글 목차">
    <h2>글 목차</h2>
    <ol>{toc}</ol>
  </nav>
  <main id="main-content" class="reading-column" tabindex="-1">
    <article>
      <p class="summary">{summary}</p>
      {sections}
    </article>
{media_region}
    <section class="sources" aria-labelledby="sources-title">
      <h2 id="sources-title">출처 목록</h2>
      <ol>{source_list}</ol>
    </section>
  </main>
  <footer class="reading-column">
    <h2>편집기 전달 안내</h2>
    <p>이 문서는 티스토리 편집기 입력 전 검토용 HTML입니다. 게시·예약·수정 작업은 수행하지 않았습니다.</p>
    <p>메타데이터와 출처를 함께 검토한 뒤 소유자가 별도로 승인해야 합니다.</p>
  </footer>
</body>
</html>
'''


def _render_section(
    index: int,
    section: DraftSection,
    sources: dict[SourceId, SourceEvidence],
) -> str:
    paragraphs = "\n".join(
        f"<p>{escape(paragraph)}</p>"
        for paragraph in section.body.split("\n\n")
        if paragraph
    )
    evidence = "\n".join(
        _render_evidence(_source_for(source_id, sources), section)
        for source_id in section.source_evidence_ids
    )
    return f'''<section class="article-section" aria-labelledby="section-{index + 1}">
  <h2 id="section-{index + 1}">{escape(section.heading)}</h2>
  {paragraphs}
  {evidence}
</section>'''


def _source_for(
    source_id: SourceId,
    sources: dict[SourceId, SourceEvidence],
) -> SourceEvidence:
    source = sources.get(source_id)
    if source is None:
        raise RenderInvariantError("SOURCE_NOT_FOUND", "/draft/sections", f"unknown source {source_id}")
    return source


def _render_evidence(source: SourceEvidence, section: DraftSection) -> str:
    url = escape(_safe_source_url(source.url), quote=True)
    title = escape(source.title)
    publisher = escape(source.publisher)
    checked = escape(source.checked_at.date().isoformat())
    claim_ids = escape(", ".join(section.claim_ids))
    return f'''<aside class="evidence-callout" aria-label="주장 근거">
  <h3>근거</h3>
  <p><a class="source-link" href="{url}">출처: {title}&nbsp;<span class="publisher">({publisher})</span></a></p>
  <p class="evidence-meta">확인일: {checked} · 주장 ID: <code class="machine-value">{claim_ids}</code></p>
</aside>'''


def _render_media(media: MediaPlaceholder) -> str:
    alt = escape(media.alt, quote=True)
    label = escape(media.label)
    if not media.alt.strip():
        raise RenderInvariantError("ACCESSIBILITY_REQUIRED", "/media/alt", "alt text is required")
    return f'''<figure class="media-placeholder">
  <img src="{_PLACEHOLDER_SVG}" alt="{alt}" width="1200" height="675">
  <figcaption>{label} · 실제 자산이 아닌 로컬 자리표시자</figcaption>
</figure>'''


def _render_source_list_item(source: SourceEvidence) -> str:
    url = escape(_safe_source_url(source.url), quote=True)
    return f'<li><a class="source-link" href="{url}">{escape(source.title)}</a> · 확인일 {source.checked_at.date().isoformat()}</li>'


def _safe_source_url(value: str) -> str:
    if any(character.isspace() or ord(character) < 0x20 for character in value):
        raise RenderInvariantError("UNSAFE_SOURCE_URL", "/source_evidence/url", "whitespace or control character")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise RenderInvariantError("UNSAFE_SOURCE_URL", "/source_evidence/url", "malformed URL") from error
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None or port is not None and port < 1:
        raise RenderInvariantError("UNSAFE_SOURCE_URL", "/source_evidence/url", "absolute http(s) URL required")
    if parsed.username is not None or parsed.password is not None:
        raise RenderInvariantError("UNSAFE_SOURCE_URL", "/source_evidence/url", "credentials are forbidden")
    return value


_STYLES: Final = '''
:root {
  --surface-paper: #fffdf9; --surface-quiet: #f6f2eb; --text-ink: #26231f;
  --text-muted: #625c54; --border-whisper: #d8d1c6; --accent-link: #075f9c;
  --focus-ring: #003f6b; --status-ready: #166534;
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-6: 24px; --space-8: 32px; --space-12: 48px;
  color-scheme: light; font-size: 1rem;
}
* { box-sizing: border-box; }
html { background: var(--surface-paper); color: var(--text-ink); }
body { margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", "Segoe UI", sans-serif; font-size: 1rem; line-height: 1.7; word-break: keep-all; }
.reading-column { inline-size: min(calc(100% - (var(--space-4) * 2)), 72ch); max-inline-size: 72ch; margin-inline: auto; }
.skip-link { position: absolute; inset-block-start: var(--space-2); inset-inline-start: var(--space-4); padding: var(--space-2) var(--space-3); background: var(--surface-paper); transform: translateY(-200%); z-index: 1; }
.skip-link:focus-visible { transform: translateY(0); }
:focus-visible { outline: 3px solid var(--focus-ring); outline-offset: var(--space-1); }
a { color: var(--accent-link); text-decoration-thickness: 1px; text-underline-offset: var(--space-1); }
a:hover, a:focus-visible { text-decoration-thickness: 2px; }
.page-header { padding-block: var(--space-12) var(--space-8); border-block-end: 1px solid var(--border-whisper); }
.eyebrow { margin: 0 0 var(--space-4); color: var(--text-muted); font-size: 0.875rem; letter-spacing: 0.04em; }
.readiness { display: grid; gap: var(--space-1); margin-block: 0 var(--space-6); padding: var(--space-4); border-inline-start: 4px solid var(--status-ready); background: var(--surface-quiet); }
.readiness strong { color: var(--status-ready); }
h1 { margin: 0; font-size: clamp(1.75rem, 6vw, 2.5rem); line-height: 1.25; letter-spacing: -0.02em; }
h2 { margin-block: var(--space-8) var(--space-3); font-size: 1.375rem; line-height: 1.4; }
h3 { margin-block: 0 var(--space-2); font-size: 1rem; }
.metadata { display: flex; flex-wrap: wrap; gap: var(--space-4); margin-block: var(--space-4) 0; color: var(--text-muted); }
.metadata div { display: flex; gap: var(--space-2); }.metadata dt { font-weight: 700; }.metadata dd { margin: 0; }
.toc { margin-block: var(--space-8); padding: var(--space-4) var(--space-6); background: var(--surface-quiet); border: 1px solid var(--border-whisper); }
.toc h2 { margin-block-start: 0; }.toc ol { margin-block-end: 0; padding-inline-start: var(--space-6); }
.summary { margin-block: 0 var(--space-8); font-size: 1.125rem; }
.article-section { padding-block-end: var(--space-6); border-block-end: 1px solid var(--border-whisper); }
.evidence-callout { margin-block: var(--space-6); padding: var(--space-4); background: var(--surface-quiet); border-inline-start: 4px solid var(--border-whisper); }
.evidence-callout p { margin-block: var(--space-1); }.evidence-meta { color: var(--text-muted); font-size: 0.875rem; }
.media-placeholder { margin: var(--space-4) 0; }.media-placeholder img { display: block; inline-size: 100%; block-size: auto; border: 1px solid var(--border-whisper); }
figcaption { margin-block-start: var(--space-2); color: var(--text-muted); }
.sources li { margin-block: var(--space-2); }.publisher { white-space: nowrap; }
.machine-value { overflow-wrap: anywhere; word-break: break-all; font-family: inherit; }
footer { margin-block-start: var(--space-12); padding-block: var(--space-6) var(--space-12); border-block-start: 1px solid var(--border-whisper); color: var(--text-muted); }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; } }
@media print { body { background: white; color: black; }.skip-link { display: none; }a[href^="http"]::after { content: " (" attr(href) ")"; overflow-wrap: anywhere; word-break: break-all; }.reading-column { inline-size: 100%; max-inline-size: none; } }
'''
