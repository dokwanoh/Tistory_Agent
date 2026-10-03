from dataclasses import asdict, dataclass, replace
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import assert_never

from ..artifacts.layout import safe_output_root
from ..contracts.json_decode import JsonDecodeError
from ..contracts.json_encode import encode_json
from .contracts import PreparationError
from .editorial import Draft, parse_draft
from .media_repair import MEDIA_DEFECTS, MediaMaterial, prepare_media
from .package import PackageInput, assemble, evidence_checked_at, write_immutable
from .provider import Provider, StageRequest
from .run_contract import PreparationRun
from .storage import StageStore
from .v2_attestation import Attestation, approve
from .v2_contracts import check_claims, claim_feedback, parse_edit
from .v2_sources import SourceSelection, bind_documents, captured
from . import prompts, v2_prompts


@dataclass(frozen=True, slots=True)
class EditBudget:
    turns: int = 0
    sources: int = 0
    media: int = 0


@dataclass(frozen=True, slots=True)
class EditorialWork:
    run: PreparationRun
    directory: Path
    selection: SourceSelection
    writing: str
    history: str
    sessions: frozenset[str]
    budget: EditBudget
    interactive_media: bool = False


@dataclass(frozen=True, slots=True)
class EditOutcome:
    package: Path | None
    budget: EditBudget


def _require_interactive_media(work: EditorialWork, directory: Path, draft: Draft) -> None:
    if not work.interactive_media:
        return
    handoff = directory / 'image-generation.handoff.json'
    if handoff.is_file():
        return
    pending = directory / 'interactive-media.pending.json'
    if not pending.exists():
        payload = {'kind': 'interactive_media_pending', 'operation_id': work.run.run_id,
            'media_directory': directory.relative_to(work.run.root).as_posix(),
            'scenes': [{'index': index, 'brief': scene.brief, 'alt': scene.alt}
                for index, scene in enumerate(draft.scenes, 1)]}
        write_immutable(pending, json.dumps(payload, ensure_ascii=False, sort_keys=True).encode())
    raise PreparationError('interactive_media_required')


def edit_package(work: EditorialWork, provider: Provider) -> EditOutcome:
    writing: str = work.writing
    selection: SourceSelection = work.selection
    budget: EditBudget = work.budget
    media: MediaMaterial | None = None
    media_directory = work.directory
    media_prompt: str = ''
    sessions = set(work.sessions)
    feedback: str = ''
    previous = ''
    policies = captured(work.directory, v2_prompts.POLICY_URLS)
    if len(policies) != len(v2_prompts.POLICY_URLS) or any(doc.access != 'full_text' for doc in policies):
        raise PreparationError('editorial_policy_sources_unavailable')
    policy_times = tuple(datetime.fromisoformat(doc.checked_at) for doc in policies)
    if any(stamp.utcoffset() is None or stamp > work.run.clock() for stamp in policy_times):
        raise PreparationError('policy_clock_invalid')
    for turn in range(budget.turns, 4):
        directory = safe_output_root(work.run.directory, f'edit-turn-{turn + 1:02}')
        directory.mkdir(exist_ok=True)
        store = StageStore(directory, provider)
        draft: Draft | None = None
        digest = sha256(writing.encode()).hexdigest()
        html = manifest = evidence = ''
        stamp = directory / 'checked-at.txt'
        if not stamp.exists():
            write_immutable(stamp, work.run.clock().isoformat().encode())
        checked = datetime.fromisoformat(stamp.read_text())
        if checked.utcoffset() is None or not selection.selected_at <= checked <= work.run.clock():
            raise PreparationError('package_clock_invalid')
        try:
            draft = parse_draft(writing, selection.candidate)
        except (PreparationError, JsonDecodeError) as error:
            feedback = error.code if isinstance(error, PreparationError) else 'writing_contract_invalid'
        if draft is not None and media is None:
            try:
                _require_interactive_media(work, media_directory, draft)
                media_store = StageStore(media_directory, provider)
                if not media_prompt:
                    media_prompt = '\n'.join((prompts.BOUNDARY, prompts.MEDIA, 'Article:', writing,
                        'Evidence:', encode_json(selection.candidate.evidence), 'Correction:', feedback))
                media = prepare_media(media_store, StageRequest('media', media_prompt, media_directory), work.history)
                sessions.add(media_store.receipt('media').session_id)
            except PreparationError as error:
                if error.code not in MEDIA_DEFECTS:
                    raise
                feedback = error.code
        if draft is not None and media is not None:
            for image in media.images:
                write_immutable(directory / 'media' / image.name, image.read_bytes())
            evidence = '\n'.join((selection.record, 'Captured evidence:', encode_json(selection.candidate.evidence),
                'Media provenance:', media.derivations, 'Policy originals:',
                json.dumps([asdict(doc) for doc in policies], ensure_ascii=False), 'Prior editorial action:', previous))
            digest = assemble(directory, PackageInput(work.run.run_id, selection.candidate, draft,
                selection.selected_at, checked, evidence, media.response, checked))
            html = (directory / 'inspection/article.html').read_text()
            manifest = (directory / 'inspection/manifest.json').read_text()
        envelope = json.dumps({'subject_sha256': digest, 'package_present': bool(html), 'writing': writing,
            'article': html, 'manifest': manifest, 'evidence': evidence,
            'documents': [asdict(doc) for doc in selection.documents], 'technical_feedback': feedback}, ensure_ascii=False)
        raw = store.run(StageRequest('edit', prompts.BOUNDARY + '\n' + v2_prompts.EDIT
            + '\nEditorial input:\n' + envelope, directory,
            media.images if media is not None else (), (*selection.candidate.urls, *v2_prompts.POLICY_URLS)))
        if store.receipt('edit').session_id in sessions:
            raise PreparationError('independent_review_session_required')
        sessions.add(store.receipt('edit').session_id)
        budget = replace(budget, turns=turn + 1)
        try:
            result = parse_edit(raw)
            if result.subject_sha256 != digest:
                raise PreparationError('editor_subject_mismatch')
        except (PreparationError, JsonDecodeError) as error:
            if isinstance(error, PreparationError) and error.code == 'source_destination_denied':
                raise
            feedback = error.code if isinstance(error, PreparationError) else 'editor_record_contract_invalid'
            continue
        previous = raw
        match result.action:
            case 'ready':
                if draft is None or media is None or not html:
                    feedback = 'ready_requires_technically_valid_package'
                    continue
                try:
                    check_claims(result, draft.title + '\n' + html, selection.documents)
                except PreparationError as error:
                    feedback = error.code + '\n' + claim_feedback(result, draft.title + '\n' + html, selection.documents)
                    continue
                package = approve(Attestation(work.run.root, work.run.run_id, directory, digest,
                    checked, min(evidence_checked_at(selection.candidate, checked), *policy_times), work.run.clock()))
                return EditOutcome(package, budget)
            case 'revise':
                if result.writing is None:
                    raise PreparationError('editor_payload_mismatch')
                try:
                    revised = parse_draft(result.writing, selection.candidate)
                    if draft is not None and tuple(scene.brief for scene in revised.scenes) != tuple(scene.brief for scene in draft.scenes):
                        if budget.media:
                            raise PreparationError('editorial_media_budget_exhausted')
                        budget = replace(budget, media=1)
                        media = None
                        media_prompt = ''
                        media_directory = safe_output_root(work.run.directory, 'media-repair-v2')
                        media_directory.mkdir(exist_ok=True)
                    writing = result.writing
                    feedback = result.notes
                except (PreparationError, JsonDecodeError) as error:
                    if isinstance(error, PreparationError) and error.code == 'editorial_media_budget_exhausted':
                        raise
                    feedback = error.code if isinstance(error, PreparationError) else 'corrected_writing_contract_invalid'
            case 'sources':
                if budget.sources:
                    raise PreparationError('editorial_source_budget_exhausted')
                budget = replace(budget, sources=1)
                extra = captured(directory, result.source_urls)
                documents = tuple({doc.url: doc for doc in (*selection.documents, *extra)}.values())
                selection = replace(selection, documents=documents,
                    candidate=bind_documents(selection.candidate, documents))
                feedback = result.notes
            case 'media':
                if budget.media:
                    raise PreparationError('editorial_media_budget_exhausted')
                budget = replace(budget, media=1)
                media = None
                media_prompt = ''
                media_directory = safe_output_root(work.run.directory, 'media-repair-v2')
                media_directory.mkdir(exist_ok=True)
                feedback = result.notes
            case 'replace_topic':
                return EditOutcome(None, budget)
            case _:
                assert_never(result.action)
    raise PreparationError('editorial_budget_exhausted')
