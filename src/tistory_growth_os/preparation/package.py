from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from hashlib import sha256
import json
from pathlib import Path
import shutil

from ..artifacts.layout import safe_output_root
from ..artifacts.package_review import payload_digest
from ..contracts.json_decode import parse_json
from ..contracts.json_ast import JsonString
from ..contracts.json_encode import encode_json
from ..domain.common import Fields, array, as_object, datetime_value, text
from ..delivery.editor_body_fingerprint import BODY_ALGORITHM, article_body_digest
from ..delivery.native_article_source import NativeAlt
from .contracts import Candidate, PreparationError, media_asset
from .editorial import Draft


@dataclass(frozen=True, slots=True)
class PackageInput:
    run_id: str
    candidate: Candidate
    draft: Draft
    selected_at: datetime
    checked_at: datetime
    evidence: str
    media_response: str
    evidence_qualified_at: datetime | None = None


def write_immutable(path: Path, body: bytes) -> None:
    if path.exists():
        if path.read_bytes() != body:
            raise PreparationError('immutable_artifact_changed')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        _ = stream.write(body)


def evidence_checked_at(candidate: Candidate, assembled_at: datetime) -> datetime:
    snapshots = candidate.evidence.get('source_snapshots')
    if snapshots is None:
        return assembled_at
    fields = Fields(candidate.evidence, '', ())
    times = [datetime_value(Fields(as_object(item, ''), '', ()), 'checked_at')
             for item in array(fields, 'source_snapshots', True)]
    if any(stamp > assembled_at for stamp in times):
        raise PreparationError('source_clock_invalid')
    return min(times)


def assemble(directory: Path, source: PackageInput) -> str:
    inspection = safe_output_root(directory, 'inspection')
    html = source.draft.html
    fields = Fields.parse(parse_json(source.media_response), '', ('assets',))
    for index, value in enumerate(array(fields, 'assets', True), 1):
        asset = media_asset(encode_json(value))
        credit_value = asset.required('credit')
        if not isinstance(credit_value, JsonString):
            raise PreparationError('credit_string_required')
        if text(asset, 'origin') == 'official' and not credit_value.value.strip():
            raise PreparationError('official_credit_required')
        if credit_value.value:
            marker = '{{MEDIA' + str(index) + '}}'
            html = html.replace(marker, marker + '<p>' + escape(credit_value.value) + '</p>')
    alts = tuple(NativeAlt(f'{index:02}.jpg', scene.alt) for index, scene in enumerate(source.draft.scenes, 1))
    if article_body_digest(html, alts) is None:
        raise PreparationError('native_body_contract_failed')
    checked = evidence_checked_at(source.candidate, source.checked_at)
    manifest = {'schema_version': 'native-immediate-v2', 'body_algorithm': BODY_ALGORITHM,
        'title': source.draft.title, 'operation_id': source.run_id,
        'event_at': source.candidate.event_at.isoformat(), 'selected_at': source.selected_at.isoformat(),
        'evidence_checked_at': (source.evidence_qualified_at or checked).isoformat(),
        'valid_until': (checked + timedelta(hours=24)).isoformat(),
        'category': source.draft.category, 'home_topic': source.draft.home_topic, 'tags': source.draft.tags,
        'representative': 'image-1', 'media': [{'asset_id': f'image-{index}', 'file': f'media/{index:02}.jpg',
            'alt': scene.alt} for index, scene in enumerate(source.draft.scenes, 1)]}
    payloads = {'manifest.json': json.dumps(manifest, ensure_ascii=False).encode(),
        'article.html': html.encode(), 'evidence.md': (source.evidence + '\n' + source.media_response).encode(),
        'quality.md': b'Deterministic structure/text/media checks passed. Separate exact-byte semantic review required.\n'}
    for index in range(1, 5):
        name = f'media/{index:02}.jpg'
        payloads[name] = safe_output_root(directory, name).read_bytes()
    payloads['quality.md'] += '\n'.join(f'{name} SHA-256 {sha256(body).hexdigest()}'
        for name, body in payloads.items() if name.startswith('media/')).encode()
    for name, body in payloads.items():
        write_immutable(safe_output_root(inspection, name), body)
    return payload_digest(payloads)


def promote(directory: Path, digest: str) -> Path:
    inspection = safe_output_root(directory, 'inspection')
    if any(path.is_symlink() for path in inspection.rglob('*')):
        raise PreparationError('package_symlink_forbidden')
    payloads = {path.relative_to(inspection).as_posix(): path.read_bytes()
                for path in inspection.rglob('*') if path.is_file() and not path.is_symlink()}
    if payload_digest(payloads) != digest:
        raise PreparationError('reviewed_package_changed')
    package = safe_output_root(directory, 'package')
    if package.exists():
        raise PreparationError('package_already_exists')
    _ = shutil.copytree(inspection, package, symlinks=False)
    return package
