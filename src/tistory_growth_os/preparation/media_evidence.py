from hashlib import sha256
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from ..artifacts.layout import ArtifactWriteError, safe_output_root
from ..contracts.json_decode import JsonDecodeError, parse_json
from ..domain.common import Fields, array, as_object, strings, text
from .contracts import PreparationError
from .package import write_immutable


@dataclass(frozen=True, slots=True)
class GenerationContext:
    codex_home: Path
    session: str
    started: float
    handoff: Path | None = None


def bind_generated_media(directory: Path, response: str, context: GenerationContext) -> str:
    fields = Fields.parse(parse_json(response), '', ('assets',))
    assets = [Fields(as_object(raw, '/assets'), '/assets', ()) for raw in array(fields, 'assets', True)]
    generated = [asset for asset in assets if text(asset, 'origin') == 'generated']
    if not generated:
        return json.dumps({'kind': 'generated_derivations', 'bindings': []})
    inventory = native_generation_evidence(context.codex_home, context.session, context.started, len(generated), context.handoff)
    inventory_fields = Fields(as_object(parse_json(inventory), ''), '', ())
    listed = {text(Fields(as_object(item, '/outputs'), '/outputs', ()), 'file')
              for item in array(inventory_fields, 'outputs', True)}
    used: set[str] = set()
    bindings: list[dict[str, str]] = []
    for asset in generated:
        source_file = asset.value.get('source_file')
        if source_file is None:
            raise PreparationError('generated_source_binding_required')
        name = text(asset, 'source_file')
        if re.fullmatch(r'exec-[0-9a-f-]{36}\.png', name) is None or name in used or name not in listed:
            raise PreparationError('generated_source_binding_invalid')
        used.add(name)
        original = safe_output_root(context.codex_home, f'generated_images/{context.session}/{name}')
        if not original.is_file():
            raise PreparationError('generated_source_binding_invalid')
        final = safe_output_root(directory, text(asset, 'file'))
        with TemporaryDirectory(prefix='tistory-derivation-') as temporary:
            converted = Path(temporary) / 'derived.jpg'
            result = subprocess.run(['/usr/bin/sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '80',
                '-Z', '900', str(original), '--out', str(converted)], capture_output=True, check=False, timeout=30)
            if result.returncode or not converted.is_file():
                raise PreparationError('generated_media_conversion_failed')
            if not final.is_file():
                final.parent.mkdir(parents=True, exist_ok=True)
                write_immutable(final, converted.read_bytes())
            elif final.read_bytes() != converted.read_bytes():
                raise PreparationError('generated_media_derivation_mismatch')
        preserved = safe_output_root(directory, 'media/originals/' + name)
        write_immutable(preserved, original.read_bytes())
        bindings.append({'file': text(asset, 'file'), 'sha256': sha256(final.read_bytes()).hexdigest(),
            'source_file': 'media/originals/' + name, 'source_sha256': sha256(original.read_bytes()).hexdigest(),
            'transformation': 'sips jpeg formatOptions=80 resizeMax=900', 'verification': 'exact_bytes'})
    return json.dumps({'kind': 'generated_derivations', 'native_inventory': inventory,
                       'bindings': bindings}, sort_keys=True)


def native_generation_evidence(
    codex_home: Path,
    session: str,
    started: float,
    count: int,
    handoff: Path | None = None,
) -> str:
    failure = PreparationError('generation_tool_evidence_required')
    if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', session):
        raise failure
    try:
        if handoff is not None:
            return _handoff_generation_evidence(codex_home, handoff, session, started, count)
        directory = safe_output_root(codex_home, f'generated_images/{session}')
        files = sorted(directory.glob('exec-*.png'))
        if len(files) != count or count < 1:
            raise failure
        outputs: list[dict[str, str]] = []
        for path in files:
            _ = safe_output_root(codex_home, path.relative_to(codex_home).as_posix())
            if not path.is_file() or not 1000 <= path.stat().st_size <= 50_000_000:
                raise failure
            if path.stat().st_mtime < started:
                raise failure
            body = path.read_bytes()
            if not body.startswith(b'\x89PNG\r\n\x1a\n'):
                raise failure
            outputs.append({'file': path.name, 'sha256': sha256(body).hexdigest()})
    except (OSError, ArtifactWriteError) as error:
        raise failure from error
    return json.dumps({'kind': 'native_generation_outputs', 'session_id': session,
                       'outputs': outputs}, sort_keys=True)


def _handoff_generation_evidence(
    codex_home: Path,
    handoff: Path,
    session: str,
    _started: float,
    count: int,
) -> str:
    failure = PreparationError('generation_tool_evidence_required')
    if handoff.is_symlink() or not handoff.is_file():
        raise failure
    try:
        fields = Fields.parse(parse_json(handoff.read_text()), '', ('kind', 'session_id', 'tool_kinds', 'outputs'))
        if (text(fields, 'kind') != 'image_generation_handoff'
                or text(fields, 'session_id') != session
                or 'image_generation' not in strings(fields, 'tool_kinds', True, r'[a-z_]+')):
            raise failure
        outputs = array(fields, 'outputs', True)
        if len(outputs) != count or count < 1:
            raise failure
        names: set[str] = set()
        records: list[dict[str, str]] = []
        directory = safe_output_root(codex_home, f'generated_images/{session}')
        for index, output in enumerate(outputs):
            output_fields = Fields.parse(output, f'/outputs/{index}', ('file', 'sha256'))
            name = text(output_fields, 'file')
            expected = text(output_fields, 'sha256')
            if (re.fullmatch(r'exec-[0-9a-f-]{36}\.png', name) is None
                    or name in names or re.fullmatch(r'[0-9a-f]{64}', expected) is None):
                raise failure
            names.add(name)
            path = safe_output_root(directory, name)
            if path.is_symlink() or not path.is_file() or path.stat().st_mtime > handoff.stat().st_mtime:
                raise failure
            body = path.read_bytes()
            if (not 1000 <= len(body) <= 50_000_000 or not body.startswith(b'\x89PNG\r\n\x1a\n')
                    or sha256(body).hexdigest() != expected):
                raise failure
            records.append({'file': name, 'sha256': expected})
    except (JsonDecodeError, OSError, TypeError, ValueError, AttributeError, ArtifactWriteError) as error:
        raise failure from error
    return json.dumps({'kind': 'native_generation_outputs', 'session_id': session,
                       'handoff': 'image_generation_handoff', 'outputs': records}, sort_keys=True)
