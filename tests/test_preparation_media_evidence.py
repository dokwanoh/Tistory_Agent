from pathlib import Path
import json
import subprocess
from hashlib import sha256

import pytest

from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.media_evidence import native_generation_evidence
from tistory_growth_os.preparation.media_repair import (
    configured_codex_home,
    handoff_session,
    recover_media_response,
)


SESSION = '01a0c105-e3f3-7231-b726-d0dd1281fb5a'


def test_configured_codex_home_uses_default_when_environment_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('CODEX_HOME', '')
    assert configured_codex_home() == Path.home() / '.codex'


def test_handoff_session_accepts_full_native_handoff(tmp_path: Path) -> None:
    handoff = tmp_path / 'image-generation.handoff.json'
    _ = handoff.write_text(json.dumps({'kind': 'image_generation_handoff', 'session_id': SESSION,
        'tool_kinds': ['image_generation'], 'outputs': []}))
    assert handoff_session(handoff) == SESSION


def test_empty_media_response_recovers_assets_from_pending_handoff(tmp_path: Path) -> None:
    (tmp_path / 'interactive-media.pending.json').write_text(json.dumps({
        'kind': 'interactive_media_pending', 'operation_id': 'operation-001',
        'media_directory': '.', 'scenes': [
            {'index': index, 'brief': f'장면 {index}', 'alt': f'설명 {index}'}
            for index in range(1, 5)
        ],
    }))
    (tmp_path / 'image-generation.handoff.json').write_text(json.dumps({
        'kind': 'image_generation_handoff', 'session_id': SESSION,
        'tool_kinds': ['image_generation'], 'outputs': [
            {'file': f'exec-00000000-0000-0000-0000-{index:012d}.png', 'sha256': '0' * 64}
            for index in range(1, 5)
        ],
    }))
    recovered = json.loads(recover_media_response(tmp_path, '{"assets":[]}'))
    assert [item['file'] for item in recovered['assets']] == [f'media/{index:02}.jpg' for index in range(1, 5)]
    assert recovered['assets'][0]['source_file'] == 'exec-00000000-0000-0000-0000-000000000001.png'


def test_native_generation_requires_same_session_fresh_outputs(tmp_path: Path) -> None:
    folder = tmp_path / 'generated_images' / SESSION
    folder.mkdir(parents=True)
    image = folder / 'exec-9425f8a4-4ed8-4f5b-aeae-4f96e96cbaf1.png'
    _ = image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 2000)
    proof = native_generation_evidence(tmp_path, SESSION, 0, 1)
    assert image.name in proof and SESSION in proof
    with pytest.raises(PreparationError, match='generation_tool_evidence_required'):
        _ = native_generation_evidence(tmp_path, SESSION, image.stat().st_mtime + 1, 1)
    with pytest.raises(PreparationError, match='generation_tool_evidence_required'):
        _ = native_generation_evidence(tmp_path, SESSION, 0, 4)


def test_native_generation_rejects_symlink_and_untrusted_identity(tmp_path: Path) -> None:
    with pytest.raises(PreparationError, match='generation_tool_evidence_required'):
        _ = native_generation_evidence(tmp_path, '../elsewhere', 0, 1)
    folder = tmp_path / 'generated_images' / SESSION
    folder.mkdir(parents=True)
    image = tmp_path / 'outside.png'
    _ = image.write_bytes(b'\x89PNG\r\n\x1a\n' + b'x' * 2000)
    (folder / 'exec-9425f8a4-4ed8-4f5b-aeae-4f96e96cbaf1.png').symlink_to(image)
    with pytest.raises(PreparationError, match='generation_tool_evidence_required'):
        _ = native_generation_evidence(tmp_path, SESSION, 0, 1)


@pytest.mark.parametrize('historical_sibling', [False, True])
def test_native_generation_accepts_only_real_image_generation_handoff(tmp_path: Path, historical_sibling: bool) -> None:
    folder = tmp_path / 'generated_images' / SESSION
    folder.mkdir(parents=True)
    image = folder / 'exec-9425f8a4-4ed8-4f5b-aeae-4f96e96cbaf1.png'
    body = b'\x89PNG\r\n\x1a\n' + b'x' * 2000
    _ = image.write_bytes(body)
    if historical_sibling:
        _ = (folder / 'exec-00000000-0000-0000-0000-000000000001.png').write_bytes(body)
    handoff = tmp_path / 'image-generation.handoff.json'
    handoff.write_text(json.dumps({'kind': 'image_generation_handoff', 'session_id': SESSION,
        'tool_kinds': ['image_generation'], 'outputs': [{'file': image.name,
        'sha256': sha256(body).hexdigest()}]}))
    from tistory_growth_os.preparation.media_evidence import native_generation_evidence
    proof = native_generation_evidence(tmp_path, SESSION, 0, 1, handoff)
    assert 'image_generation_handoff' in proof
    handoff.write_text(handoff.read_text().replace('image_generation', 'command_execution'))
    with pytest.raises(PreparationError, match='generation_tool_evidence_required'):
        _ = native_generation_evidence(tmp_path, SESSION, 0, 1, handoff)
    with pytest.raises(PreparationError, match='generation_tool_evidence_required'):
        _ = native_generation_evidence(tmp_path, 'wrong-session', 0, 1, handoff)


def test_native_generation_converts_malformed_handoff_to_evidence_hold(tmp_path: Path) -> None:
    handoff = tmp_path / 'image-generation.handoff.json'
    _ = handoff.write_text('{"kind":"image_generation_handoff"')
    with pytest.raises(PreparationError, match='generation_tool_evidence_required'):
        _ = native_generation_evidence(tmp_path, SESSION, 0, 1, handoff)


@pytest.mark.parametrize(('source_name', 'replace_final', 'reason'), [
    ('', False, ''),
    ('../outside.png', False, 'generated_source_binding_invalid'),
    ('exec-00000000-0000-0000-0000-000000000000.png', False, 'generated_source_binding_invalid'),
    ('', True, 'generated_media_derivation_mismatch'),
    ('MISSING', False, 'generated_source_binding_required'),
])
def test_original_binding_verifies_conversion_and_rejects_substitution(
    tmp_path: Path, source_name: str, replace_final: bool, reason: str,
) -> None:
    from tistory_growth_os.preparation.media_evidence import bind_generated_media, GenerationContext
    folder = tmp_path / 'generated_images' / SESSION
    folder.mkdir(parents=True)
    ppm = tmp_path / 'fixture.ppm'
    _ = ppm.write_bytes(b'P6\n400 400\n255\n' + bytes(i % 256 for i in range(480000)))
    original = folder / 'exec-9425f8a4-4ed8-4f5b-aeae-4f96e96cbaf1.png'
    _ = subprocess.run(['/usr/bin/sips', '-s', 'format', 'png', str(ppm), '--out', str(original)],
                       capture_output=True, check=True)
    directory = tmp_path / 'run'
    (directory / 'media').mkdir(parents=True)
    final = directory / 'media/01.jpg'
    _ = subprocess.run(['/usr/bin/sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', '80',
                        '-Z', '900', str(original), '--out', str(final)], capture_output=True, check=True)
    response = json.dumps({'assets': [{'file': 'media/01.jpg', 'origin': 'generated',
        'source_file': source_name or original.name, 'source_url': 'generated', 'rights_basis': 'fixture',
        'credit': '', 'scene': 'fixture'}]})
    response = response.replace(', "source_file": "MISSING"', '')
    context = GenerationContext(tmp_path, SESSION, 0)
    if replace_final:
        _ = final.write_bytes(b'substituted image')
    if reason:
        with pytest.raises(PreparationError, match=reason):
            _ = bind_generated_media(directory, response, context)
    else:
        proof = bind_generated_media(directory, response, context)
        assert sha256(original.read_bytes()).hexdigest() in proof
        assert sha256(final.read_bytes()).hexdigest() in proof
        assert 'media/01.jpg' in proof


def test_original_binding_derives_missing_final_from_native_png(tmp_path: Path) -> None:
    from tistory_growth_os.preparation.media_evidence import bind_generated_media, GenerationContext
    folder = tmp_path / 'generated_images' / SESSION
    folder.mkdir(parents=True)
    ppm = tmp_path / 'fixture.ppm'
    _ = ppm.write_bytes(b'P6\n400 400\n255\n' + bytes(i % 256 for i in range(480000)))
    original = folder / 'exec-9425f8a4-4ed8-4f5b-aeae-4f96e96cbaf1.png'
    _ = subprocess.run(['/usr/bin/sips', '-s', 'format', 'png', str(ppm), '--out', str(original)],
                       capture_output=True, check=True)
    directory = tmp_path / 'run'
    (directory / 'media').mkdir(parents=True)
    response = json.dumps({'assets': [{'file': 'media/01.jpg', 'origin': 'generated',
        'source_file': original.name, 'source_url': 'generated', 'rights_basis': 'fixture',
        'credit': '', 'scene': 'fixture'}]})
    proof = bind_generated_media(directory, response, GenerationContext(tmp_path, SESSION, 0))
    assert (directory / 'media/01.jpg').is_file()
    assert sha256(original.read_bytes()).hexdigest() in proof
