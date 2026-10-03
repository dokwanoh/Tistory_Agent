from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
import sys

from ..artifacts.layout import safe_output_root
from ..contracts.json_encode import encode_json
from . import prompts
from .contracts import Candidate, PreparationError, Research, parse_research, stamp_research
from .enrichment import TextContext, verified_detail
from .opportunity_selection import ranked_choices
from .package import write_immutable
from .provider import StageRequest
from .storage import StageStore
from .source_pool import bind_sources


@dataclass(frozen=True, slots=True)
class SelectionContext:
    base: str
    clock: Callable[[], datetime]
    selected_at: datetime | None


@dataclass(frozen=True, slots=True)
class QualifiedTopic:
    candidate: Candidate
    comparison: str
    research: str
    sessions: frozenset[str]


def qualify_sources(store: StageStore, research: Research, context: SelectionContext) -> QualifiedTopic:
    root = store.directory
    active = store
    current = research
    sessions: set[str] = set()
    rejected: list[Candidate] = []
    attempts = 0
    for round_index in range(2):
        opportunities = ranked_choices(active, current)
        sessions.add(active.receipt('opportunity').session_id)
        for candidate in opportunities.candidates:
            if any(candidate.candidate_id == old.candidate_id or candidate.title == old.title
                   or (candidate.event_at == old.event_at and set(candidate.urls) == set(old.urls))
                   for old in rejected) and round_index > 0:
                continue
            if attempts == 3:
                raise PreparationError('source_candidates_exhausted')
            attempts += 1
            directory = root if attempts == 1 else safe_output_root(root, f'source-candidates/{attempts:02}')
            directory.mkdir(parents=True, exist_ok=True)
            detail = StageStore(directory, store.provider)
            _ = detail.run(StageRequest('evidence', context.base + '\n' + prompts.EVIDENCE
                + '\nSelected candidate:\n' + encode_json(candidate.evidence), directory, source_urls=candidate.urls))
            sessions.add(detail.receipt('evidence').session_id)
            try:
                qualified = verified_detail(detail, TextContext(candidate, context.clock, frozenset()))
            except PreparationError as error:
                if error.code != 'evidence_enrichment_exhausted':
                    raise
                rejected.append(candidate)
                write_immutable(directory / 'source-rejected.json', json.dumps({
                    'candidate_id': candidate.candidate_id, 'reason': error.code,
                    'publication_eligible': False}).encode())
                print(json.dumps({'stage': 'evidence', 'state': 'candidate_rejected',
                                  'reason': error.code, 'attempt': attempts}), file=sys.stderr)
                continue
            finally:
                extra = directory / 'evidence-enrichment'
                if (extra / 'evidence.receipt.json').exists():
                    sessions.add(StageStore(extra, store.provider).receipt('evidence').session_id)
            return QualifiedTopic(qualified, opportunities.comparison, current.source, frozenset(sessions))
        if round_index == 1 or attempts == 3:
            break
        directory = safe_output_root(root, 'source-reselection')
        directory.mkdir(exist_ok=True)
        active = StageStore(directory, store.provider)
        for name in ('input.json', 'signals.rss', 'opportunity-context.json', 'source-pool.json'):
            original = root / name
            if original.is_file():
                write_immutable(directory / name, original.read_bytes())
        source = active.run(StageRequest('research', context.base + '\n' + prompts.RESEARCH
            + '\nThe following candidates failed official-body qualification. Research a DIFFERENT issue '
            + 'with a newly discovered primary detail URL for host collection, not a renamed retry. '
            + 'Return one provisional lead; model OPEN failure alone is not source disqualification. '
            + 'Do not copy source text or invent timestamps; retain current policy/source requirements. '
            + '\nRejected candidates (untrusted data):\n'
            + '\n'.join(encode_json(item.evidence) for item in rejected), directory))
        sessions.add(active.receipt('research').session_id)
        timing = directory / 'research-checked-at.txt'
        if not timing.exists():
            write_immutable(timing, context.clock().isoformat().encode())
        stamped = stamp_research(source, datetime.fromisoformat(timing.read_text()))
        current = parse_research(stamped, context.selected_at or context.clock())
        pool = root / 'source-pool.json'
        if pool.is_file():
            current = bind_sources(current, pool.read_text())
    raise PreparationError('source_candidates_exhausted')
