from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from ..domain.common import QualityStatus
from ..domain.content import ArticleDraft, OfflineRunRequest
from ..domain.results import PipelineBlocked, PipelineReady, PipelineResult
from ..domain.state import (
    PipelineEvent,
    PipelineState,
    TransitionAccepted,
    transition,
)
from ..policy.gates import evaluate_policy
from ..rendering.html import (
    RenderDocument,
    render_article_html,
)
from ..rendering.metadata import build_review_metadata
from ..rendering.rollback import build_local_rollback

from .brief import build_content_brief
from .draft import build_article_draft
from .evidence import CanonicalInputDigest, build_evidence_pack
from .quality import evaluate_quality


def run_offline_pipeline(
    root: Path,
    request: OfflineRunRequest,
    input_digest: CanonicalInputDigest,
) -> PipelineResult:
    state = PipelineState.TOPIC_VALIDATED
    history = [state]
    evidence = build_evidence_pack(request, input_digest)
    state = _advance(state, PipelineEvent.EVIDENCE_READY, history)
    brief = build_content_brief(request, input_digest)
    state = _advance(state, PipelineEvent.BRIEF_READY, history)
    draft = build_article_draft(request, brief, input_digest)
    state = _advance(state, PipelineEvent.DRAFT_READY, history)
    policy = evaluate_policy(root, request)
    quality = evaluate_quality(request, draft, policy)
    if not policy.approval_eligible or quality.status.value != "pass":
        evaluated_draft = replace(draft, quality_status=QualityStatus.BLOCKED)
        event = (
            PipelineEvent.POLICY_FAILED
            if not policy.approval_eligible
            else PipelineEvent.QUALITY_FAILED
        )
        _ = _advance(state, event, history)
        codes = tuple(dict.fromkeys(item.code.value for item in quality.findings))
        return PipelineBlocked(
            request,
            evidence,
            brief,
            evaluated_draft,
            policy,
            quality,
            tuple(history),
            codes,
        )
    state = _advance(state, PipelineEvent.QUALITY_PASSED, history)
    evaluated_draft = replace(draft, quality_status=QualityStatus.PASS)
    body_hash = _draft_body_hash(evaluated_draft)
    document = RenderDocument(request, evaluated_draft, quality, body_hash)
    article_html = render_article_html(document)
    state = _advance(state, PipelineEvent.PACKAGE_READY, history)
    return PipelineReady(
        request,
        evidence,
        brief,
        evaluated_draft,
        policy,
        quality,
        tuple(history),
        body_hash,
        article_html,
        build_review_metadata(document),
        build_local_rollback(("bundle/article.html", "bundle/metadata.json")),
    )


def _advance(
    state: PipelineState,
    event: PipelineEvent,
    history: list[PipelineState],
) -> PipelineState:
    result = transition(state, event)
    if not isinstance(result, TransitionAccepted):
        raise RuntimeError(f"invalid internal transition: {state} + {event}")
    history.append(result.next_state)
    return result.next_state


def _draft_body_hash(draft: ArticleDraft) -> str:
    parts = [
        draft.draft_id,
        draft.version,
        draft.title,
        draft.summary,
        draft.quality_status.value,
    ]
    for section in draft.sections:
        parts.extend((section.section_id, section.heading, section.body))
        parts.extend(section.claim_ids)
        parts.extend(section.source_evidence_ids)
    digest = sha256("\x00".join(parts).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
