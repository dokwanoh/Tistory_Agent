from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal, Protocol

from ..contracts.json_decode import JsonDecodeError, parse_json
from ..domain.common import Fields, as_object, text
from .contracts import PreparationError
from .source_schema import writing_schema
from .decision_spans import DecisionSpans
from .package import write_immutable
from .source_access import bind_detail_sources, collect_context
from . import prompts
from ..site_config import configured_model, require_model_execution


Stage = Literal['research', 'opportunity', 'selection', 'evidence', 'writing', 'text_review', 'media', 'review',
                'discovery', 'decision', 'edit']
MODEL: Final = 'gpt-6-astra'
RESERVED_MODEL: Final = 'gpt-reserve'
SKILL_BUDGET_WARNING: Final = (
    'Skill descriptions were shortened to fit the skills context budget. Codex can still see every skill, '
    'but some descriptions are shorter. Disable unused skills or plugins to leave more room for the rest.')
STAGE_MODELS: Final[Mapping[Stage, str]] = MappingProxyType({
    'discovery': RESERVED_MODEL,
    'research': RESERVED_MODEL,
    'opportunity': RESERVED_MODEL,
    'selection': RESERVED_MODEL,
    'evidence': RESERVED_MODEL,
    'writing': RESERVED_MODEL,
    'text_review': RESERVED_MODEL,
    'media': RESERVED_MODEL,
    'review': RESERVED_MODEL,
    'decision': RESERVED_MODEL,
    'edit': RESERVED_MODEL,
})
SCHEMAS: Final = Path(__file__).resolve().parents[3] / 'contracts/preparation'


def model_for_stage(stage: Stage) -> str:
    return configured_model(stage)


@dataclass(frozen=True, slots=True)
class StageRequest:
    stage: Stage
    prompt: str
    directory: Path
    images: tuple[Path, ...] = ()
    source_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StageResponse:
    response: str
    session_id: str
    tool_kinds: tuple[str, ...]
    sources: str = ''
    warnings: tuple[str, ...] = ()


class Provider(Protocol):
    def __call__(self, request: StageRequest) -> StageResponse: ...


class ProviderFailureClass(StrEnum):
    AUTHENTICATION = 'authentication'
    RATE_LIMITED = 'rate_limited'
    SCHEMA_REJECTED = 'schema_rejected'
    REQUEST_TOO_LARGE = 'request_too_large'
    NETWORK_ERROR = 'network_error'
    SERVICE_UNAVAILABLE = 'service_unavailable'
    UNCLASSIFIED = 'unclassified'


def classify_provider_failure(stderr: str) -> ProviderFailureClass:
    """Map CLI stderr to a safe category without retaining arbitrary text."""
    lowered = stderr.casefold()
    statuses = re.findall(r'\b(?:http(?:/\d(?:\.\d)?)?|status(?:\s+code)?)\s*[:=]?\s*(401|429|50[234])\b', lowered)
    if 'schema' in lowered and any(word in lowered for word in ('invalid', 'unsupported', 'reject', 'limit')):
        return ProviderFailureClass.SCHEMA_REJECTED
    if '401' in statuses or any(word in lowered for word in ('unauthorized', 'authentication required', 'not logged in', 'invalid api key')):
        return ProviderFailureClass.AUTHENTICATION
    if '429' in statuses or any(word in lowered for word in ('rate limit', 'too many requests')):
        return ProviderFailureClass.RATE_LIMITED
    if any(word in lowered for word in ('request too large', 'payload too large', 'context length', 'token limit',
                                       'input_too_large', 'exceeds the maximum length')):
        return ProviderFailureClass.REQUEST_TOO_LARGE
    if any(status in statuses for status in ('502', '503', '504')) or any(word in lowered for word in ('service unavailable', 'overloaded')):
        return ProviderFailureClass.SERVICE_UNAVAILABLE
    if any(word in lowered for word in ('connection refused', 'connection reset', 'failed to connect', 'timed out', 'dns error')):
        return ProviderFailureClass.NETWORK_ERROR
    return ProviderFailureClass.UNCLASSIFIED


def completion(events: str, model: str = MODEL) -> StageResponse:
    session = ''
    response = ''
    completed = 0
    kinds: list[str] = []
    warnings: list[str] = []
    for index, line in enumerate(events.split('\n')):
        if not line.strip():
            continue
        line = re.sub(r'^(\{"type":"item\.(?:started|completed)","item":\{)"id":("item_[0-9]+","type":"web_search","id":)',
                      r'\1"cli_item_id":\2', line, count=1)
        try:
            fields = Fields(as_object(parse_json(line), ''), '', ())
        except JsonDecodeError as error:
            raise PreparationError(f'provider_event_json_{index}_{error.issue.offset}') from error
        kind = text(fields, 'type')
        if kind in ('error', 'turn.failed'):
            raise PreparationError('provider_turn_failed')
        if kind == 'thread.started':
            if session:
                raise PreparationError('provider_multiple_sessions')
            session = text(fields, 'thread_id')
        if kind == 'turn.completed':
            completed += 1
        if kind == 'item.completed':
            item = Fields(as_object(fields.required('item'), '/item'), '/item', ())
            name = text(item, 'type')
            if name == 'error' and text(item, 'message') == SKILL_BUDGET_WARNING:
                warnings.append('skill_descriptions_shortened')
                continue
            if name == 'agent_message':
                response = text(item, 'text')
            elif name != 'reasoning':
                kinds.append(name)
    if not session or not response:
        raise PreparationError('provider_completion_required')
    if (model != RESERVED_MODEL or warnings) and completed != 1:
        raise PreparationError('provider_completion_required')
    return StageResponse(response, session, tuple(kinds), warnings=tuple(warnings))


def require_stage_tools(request: StageRequest, parsed: StageResponse) -> None:
    allowed = {'web_search', 'image_generation', 'command_execution', 'file_change'}
    text_only = request.stage in ('selection', 'writing', 'evidence', 'text_review', 'review', 'decision', 'edit')
    reason = ''
    if any(kind not in allowed for kind in parsed.tool_kinds):
        reason = 'unexpected_provider_tool'
    elif text_only and parsed.tool_kinds:
        reason = 'text_only_stage_used_tools'
    elif request.stage in ('research', 'opportunity', 'discovery') and 'web_search' not in parsed.tool_kinds:
        reason = 'live_research_evidence_required'
    if reason:
        write_immutable(request.directory / f'{request.stage}.error.json', json.dumps({
            'stage': request.stage, 'reason': reason, 'tool_kinds': parsed.tool_kinds}).encode())
        raise PreparationError(reason)


def codex_provider(request: StageRequest) -> StageResponse:
    require_model_execution()
    grounded = request.stage in ('evidence', 'text_review', 'review', 'decision', 'edit')
    sources = collect_context(request.directory, request.prompt, request.source_urls) if grounded else ''
    schema = SCHEMAS / f'{request.stage}.json'
    spans = DecisionSpans.from_sources(sources) if request.stage == 'decision' else None
    if spans is not None:
        schema = request.directory / 'decision.schema.json'
        write_immutable(schema, spans.schema().encode())
    if request.stage == 'writing':
        if not request.source_urls:
            raise PreparationError('writing_source_catalog_required')
        schema = request.directory / 'writing.schema.json'
        write_immutable(schema, writing_schema(request.source_urls).encode())
    online = request.stage in ('research', 'opportunity', 'media', 'discovery')
    argv = ['codex', *(['--search'] if online else ['-c', 'web_search="disabled"']), 'exec', '--json', '--ephemeral', '--sandbox',
            'workspace-write' if request.stage == 'media' else 'read-only',
            '--model', model_for_stage(request.stage), '--output-schema', str(schema),
            '--output-last-message', str(request.directory / f'{request.stage}.completion.json'),
            '--cd', str(request.directory)]
    for image in request.images:
        argv.extend(('--image', str(image)))
    argv.append('-')
    prompt = request.prompt + (spans.prompt() if spans is not None else '')
    if grounded:
        prompt = prompt.replace(prompts.EVIDENCE, prompts.CAPTURED_EVIDENCE)
        prompt = prompt.replace(prompts.TEXT_REVIEW, prompts.CAPTURED_TEXT_REVIEW)
        prompt = prompt.replace(prompts.REVIEW, prompts.CAPTURED_REVIEW)
        prompt = prompt.replace(prompts.COLLECTED_SOURCES, '')
        prompt += ('\nSOURCE ACCESS CONTRACT: No tools. Read ONLY the host-collected bodies below and '
            + 'supplied immutable source_snapshots. '
            + 'Collection is not approval. Judge claim support independently against actual text. '
            + 'Do not treat search snippets or paraphrases as original bodies. Preserve actual source '
            + 'checked_at, never claim a new visit. If more evidence is needed, use the current output '
            + 'schema: edit action sources with source_urls/notes, decision NONE for unsuitable evidence, '
            + 'or legacy issues/support where that schema requires it. '
            + 'Do not invent inaccessible content.\nHost source documents:\n' + sources)
    result = subprocess.run(argv, input=prompt, text=True, capture_output=True,
                            check=False, timeout=900)
    if result.returncode != 0:
        diagnostic = {'stage': request.stage, 'exit_code': result.returncode,
                      'stderr_sha256': sha256(result.stderr.encode()).hexdigest(),
                      'stderr_bytes': len(result.stderr.encode()),
                      'stderr_classification': classify_provider_failure(result.stderr).value}
        with (request.directory / f'{request.stage}.error.json').open('x') as stream:
            _ = stream.write(json.dumps(diagnostic))
        raise PreparationError('provider_execution_failed')
    parsed = completion(result.stdout, model=model_for_stage(request.stage))
    if parsed.warnings:
        write_immutable(request.directory / f'{request.stage}.warnings.json', json.dumps({
            'stage': request.stage, 'warnings': parsed.warnings}).encode())
    require_stage_tools(request, parsed)
    response = bind_detail_sources(parsed.response, sources) if request.stage == 'evidence' else parsed.response
    if spans is not None:
        response = spans.resolve(response)
    return StageResponse(response, parsed.session_id, parsed.tool_kinds, sources, parsed.warnings)
