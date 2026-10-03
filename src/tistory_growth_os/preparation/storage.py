from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys

from ..artifacts.layout import safe_output_root
from ..contracts.json_decode import parse_json
from ..contracts.json_ast import JsonArray, JsonObject, JsonString
from ..contracts.json_encode import encode_json
from ..domain.common import Fields, array, as_object, text
from ..research.intake import public_source_url
from .contracts import PreparationError, media_asset
from .provider import Provider, Stage, StageRequest, StageResponse


def receipt_fields(raw: str) -> Fields:
    value = as_object(parse_json(raw), '')
    keys = ('request_sha256', 'response_sha256', 'session_id', 'tool_kinds')
    if value.get('sources_sha256') is not None:
        keys += ('sources_sha256',)
    return Fields.parse(value, '', keys)


@dataclass(frozen=True, slots=True)
class StageStore:
    directory: Path
    provider: Provider

    def receipt(self, stage: Stage) -> StageResponse:
        fields = receipt_fields((self.directory / f'{stage}.receipt.json').read_text())
        kinds: list[str] = []
        for value in array(fields, 'tool_kinds', False):
            if not isinstance(value, JsonString) or not value.value:
                raise PreparationError('receipt_tool_type_invalid')
            kinds.append(value.value)
        return StageResponse('', text(fields, 'session_id'), tuple(kinds))

    def run(self, request: StageRequest) -> str:
        response_path = self.directory / f'{request.stage}.json'
        receipt_path = self.directory / f'{request.stage}.receipt.json'
        request_digest = sha256((request.prompt + (
            '\nSource catalog:\n' + json.dumps(request.source_urls)
            if request.stage in ('writing', 'decision', 'edit') and request.source_urls else '')).encode()).hexdigest()
        if receipt_path.exists():
            fields = receipt_fields(receipt_path.read_text())
            raw = response_path.read_text()
            if (text(fields, 'request_sha256') != request_digest
                    or text(fields, 'response_sha256') != sha256(raw.encode()).hexdigest()):
                raise PreparationError('checkpoint_changed')
            if fields.value.get('sources_sha256') is not None:
                from .source_access import checked_snapshot
                _ = checked_snapshot(self.directory, request.stage)
            print(json.dumps({'stage': request.stage, 'state': 'checkpoint_reused'}), file=sys.stderr)
            return raw
        if (request.stage == 'evidence'
                and any((self.directory / name).exists() for name in ('writing.attempt', 'writing.receipt.json'))):
            raise PreparationError('source_workflow_changed')
        attempt = self.directory / f'{request.stage}.attempt'
        try:
            with attempt.open('x') as stream:
                _ = stream.write(request_digest)
        except FileExistsError:
            raise PreparationError('stage_attempt_uncertain') from None
        print(json.dumps({'stage': request.stage, 'state': 'started'}), file=sys.stderr)
        result = self.provider(request)
        if request.stage not in ('discovery', 'decision', 'edit'):
            _ = parse_json(result.response)
        source_binding: dict[str, str] = {}
        if result.sources:
            with (self.directory / f'{request.stage}.sources.json').open('x') as stream:
                _ = stream.write(result.sources)
            source_binding['sources_sha256'] = sha256(result.sources.encode()).hexdigest()
        with response_path.open('x') as stream:
            _ = stream.write(result.response)
        with receipt_path.open('x') as stream:
            _ = stream.write(json.dumps({'request_sha256': request_digest,
                'response_sha256': sha256(result.response.encode()).hexdigest(),
                'session_id': result.session_id, 'tool_kinds': result.tool_kinds, **source_binding}))
        print(json.dumps({'stage': request.stage, 'state': 'response_recorded'}), file=sys.stderr)
        return result.response


def prior_research_leads(root: Path) -> str:
    paths = sorted((root / '.artifacts/preparation').glob('*/research.json'),
                   key=lambda path: path.stat().st_mtime, reverse=True)[:2]
    candidates: list[JsonObject] = []
    for path in paths:
        _ = safe_output_root(root, path.relative_to(root).as_posix())
        if path.is_symlink() or path.stat().st_size > 200_000:
            raise PreparationError('prior_research_input_unsafe')
        fields = Fields(as_object(parse_json(path.read_text()), ''), '', ())
        candidates.extend(as_object(value, '/candidates') for value in array(fields, 'candidates', False)[:5])
    return encode_json(JsonArray(tuple(candidates)))


def history_snapshot(root: Path) -> str:
    candidates = {path.parent: path for pattern in ('**/publish-manifest.json', '**/manifest.json')
                  for path in (root / 'content').glob(pattern)}
    for path in (root / '.artifacts/preparation').glob('**/package/manifest.json'):
        candidates[path.parent] = path
    manifests = sorted(candidates.values(), key=lambda path: path.stat().st_mtime, reverse=True)[:5]
    history: list[dict[str, str]] = []
    for path in manifests:
        _ = safe_output_root(root, path.relative_to(root).as_posix())
        records = [path.read_text()]
        for relative in ('media/PROVENANCE.md', 'media/photo-v3-record.md'):
            source = safe_output_root(path.parent, relative)
            if source.is_file():
                records.append(source.read_text()[:12000])
        hashes = [sha256(media.read_bytes()).hexdigest() for media in (path.parent / 'media').glob('*.jpg')
                  if media.is_file() and not media.is_symlink() and media.stat().st_size <= 5_000_000]
        history.append({'identity': path.parent.relative_to(root).as_posix(), 'record': '\n'.join(records),
                        'asset_hashes': ','.join(hashes)})
    return json.dumps({'inspected': history, 'history_complete': len(history) == 5}, ensure_ascii=False)


def media_files(directory: Path, response: str) -> tuple[Path, ...]:
    fields = Fields.parse(parse_json(response), '', ('assets',))
    paths: list[Path] = []
    hashes: set[str] = set()
    for index, raw in enumerate(array(fields, 'assets', True), 1):
        asset = media_asset(encode_json(raw))
        origin = text(asset, 'origin')
        if origin not in ('official', 'generated'):
            raise PreparationError('media_origin_invalid')
        if origin == 'official' and (not public_source_url(text(asset, 'source_url'))
                                     or 'https://' not in text(asset, 'rights_basis')):
            raise PreparationError('official_provenance_required')
        if origin == 'generated' and text(asset, 'source_url') != 'generated':
            raise PreparationError('generated_provenance_invalid')
        if text(asset, 'file') != f'media/{index:02}.jpg':
            raise PreparationError('media_filename_mismatch')
        path = safe_output_root(directory, text(asset, 'file'))
        if not path.is_file() or not 1000 <= path.stat().st_size <= 1_000_000:
            raise PreparationError('media_missing_or_oversized')
        body = path.read_bytes()
        if not body.startswith(b'\xff\xd8\xff') or not body.endswith(b'\xff\xd9'):
            raise PreparationError('jpeg_required')
        decoded = subprocess.run(['/usr/bin/sips', '-g', 'pixelWidth', '-g', 'pixelHeight', str(path)],
                                 capture_output=True, text=True, timeout=10, check=False)
        dimensions = [match.group(1) for match in re.finditer(r'pixel(?:Width|Height): (\d+)', decoded.stdout)]
        if decoded.returncode or len(dimensions) != 2 or any(not 1 <= int(n) <= 900 for n in dimensions):
            raise PreparationError('jpeg_decode_failed')
        hashes.add(sha256(body).hexdigest())
        for key in ('origin', 'rights_basis', 'scene'):
            _ = text(asset, key)
        paths.append(path)
    if len(paths) != 4 or len(hashes) != 4:
        raise PreparationError('four_distinct_images_required')
    return tuple(paths)
