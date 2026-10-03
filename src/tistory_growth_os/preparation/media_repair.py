from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Final

from ..contracts.json_decode import JsonDecodeError, parse_json
from ..domain.common import Fields, array, as_object, boolean, strings, text
from .contracts import CHECKS, PreparationError
from .media_evidence import GenerationContext, bind_generated_media
from .package import write_immutable
from .provider import StageRequest
from .storage import StageStore, media_files


MEDIA_DEFECTS: Final = frozenset(('media_missing_or_oversized', 'jpeg_required', 'jpeg_decode_failed',
    'four_distinct_images_required', 'historical_media_reuse', 'official_credit_required',
    'official_provenance_required', 'media_filename_mismatch', 'media_review_needs_enrichment'))


@dataclass(frozen=True, slots=True)
class MediaMaterial:
    response: str
    images: tuple[Path, ...]
    derivations: str


def configured_codex_home() -> Path:
    configured = os.environ.get('CODEX_HOME', '').strip()
    return Path(configured) if configured else Path.home() / '.codex'


def handoff_session(handoff: Path) -> str:
    fields = Fields.parse(parse_json(handoff.read_text()), '', ('kind', 'session_id', 'tool_kinds', 'outputs'))
    return text(fields, 'session_id')


def recover_media_response(directory: Path, response: str) -> str:
    fields = Fields.parse(parse_json(response), '', ('assets',))
    if array(fields, 'assets', False):
        return response
    pending = directory / 'interactive-media.pending.json'
    handoff = directory / 'image-generation.handoff.json'
    if not pending.is_file() or not handoff.is_file():
        return response
    pending_fields = Fields.parse(parse_json(pending.read_text()), '',
                                  ('kind', 'operation_id', 'media_directory', 'scenes'))
    scenes = array(pending_fields, 'scenes', True)
    handoff_fields = Fields.parse(parse_json(handoff.read_text()), '',
                                  ('kind', 'session_id', 'tool_kinds', 'outputs'))
    outputs = array(handoff_fields, 'outputs', True)
    if len(scenes) != 4 or len(outputs) != 4:
        raise PreparationError('generation_tool_evidence_required')
    assets: list[dict[str, str]] = []
    for index, (scene_raw, output_raw) in enumerate(zip(scenes, outputs, strict=True), 1):
        scene = Fields(as_object(scene_raw, f'/scenes/{index - 1}'), f'/scenes/{index - 1}', ())
        output = Fields.parse(output_raw, f'/outputs/{index - 1}', ('file', 'sha256'))
        source_file = text(output, 'file')
        if re.fullmatch(r'exec-[0-9a-f-]{36}\.png', source_file) is None:
            raise PreparationError('generation_tool_evidence_required')
        assets.append({'file': f'media/{index:02}.jpg', 'origin': 'generated',
                       'source_file': source_file, 'source_url': 'generated',
                       'rights_basis': 'Built-in native image generation; immutable handoff verified.',
                       'credit': '', 'scene': text(scene, 'brief')})
    return json.dumps({'assets': assets}, ensure_ascii=False, separators=(',', ':'))


def prepare_media(store: StageStore, request: StageRequest, history: str) -> MediaMaterial:
    response = store.run(request)
    codex_home = configured_codex_home()
    handoff = store.directory / 'image-generation.handoff.json'
    handoff_path = handoff if handoff.is_file() else None
    session = store.receipt('media').session_id
    started = (handoff.stat().st_mtime if handoff_path is not None
               else (store.directory / 'media.attempt').stat().st_mtime)
    if handoff_path is not None:
        try:
            session = handoff_session(handoff)
        except (JsonDecodeError, OSError, TypeError, ValueError, AttributeError) as error:
            raise PreparationError('generation_tool_evidence_required') from error
    context = GenerationContext(codex_home, session, started, handoff_path)
    response = recover_media_response(store.directory, response)
    derivations = bind_generated_media(store.directory, response, context)
    images = media_files(store.directory, response)
    write_immutable(store.directory / 'media-derivations.json', derivations.encode())
    if any(sha256(image.read_bytes()).hexdigest() in history for image in images):
        raise PreparationError('historical_media_reuse')
    return MediaMaterial(response, images, derivations)


def media_repair_eligible(response: str, digest: str) -> bool:
    fields = Fields.parse(parse_json(response), '', ('subject_sha256', 'approved', 'checks', 'issues'))
    checks = Fields.parse(fields.required('checks'), '/checks', CHECKS)
    failed = {name for name in CHECKS if not boolean(checks, name)}
    return (text(fields, 'subject_sha256') == digest and not boolean(fields, 'approved')
        and bool(strings(fields, 'issues', False, r'[\s\S]+'))
        and bool(failed & {'images', 'diversity', 'rights'})
        and failed <= {'images', 'diversity', 'rights', 'facts', 'reader_value', 'voice',
                       'originality', 'web_text_accessibility'})
