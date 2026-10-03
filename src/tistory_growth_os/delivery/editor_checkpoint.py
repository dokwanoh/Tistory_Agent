from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from playwright.sync_api import Page

from ..contracts.json_decode import parse_json
from ..domain.common import Fields, array, identifier, text
from ..domain.ids import MediaId
from .editor_correction import OwnedEditor
from .immediate_media import media_bindings
from .native_article_source import NativeAlt, compose_native_article
from .playwright_editor_mode import select_editor_mode
from .playwright_observation import UploadedAsset


class EditorCheckpointError(ValueError):
    code: str

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def record_editor(path: Path, digest: str, editor: OwnedEditor) -> None:
    payload = json.dumps({'digest': digest, 'editor': {'title': editor.title, 'template': editor.template,
        'body_digest': editor.body_digest, 'media': [asdict(item) for item in editor.media],
        'uploads': [asdict(item) for item in media_bindings(editor.uploads)]}}, ensure_ascii=False)
    if path.exists():
        if path.read_text() != payload:
            raise EditorCheckpointError('editor_checkpoint_conflict')
        return
    with path.open('x') as target:
        _ = target.write(payload)
    path.chmod(0o600)


def read_editor(path: Path, digest: str, page: Page) -> OwnedEditor:
    if path.is_symlink():
        raise EditorCheckpointError('editor_checkpoint_symlink')
    fields = Fields.parse(parse_json(path.read_text()), '', ('digest', 'editor'))
    if identifier(fields, 'digest', r'[0-9a-f]{64}') != digest:
        raise EditorCheckpointError('editor_checkpoint_identity')
    item = Fields.parse(fields.required('editor'), '/editor', ('title', 'template', 'body_digest', 'media', 'uploads'))
    media: list[NativeAlt] = []
    uploads: list[UploadedAsset] = []
    for raw in array(item, 'media', True):
        entry = Fields.parse(raw, '/media', ('filename', 'alt'))
        media.append(NativeAlt(text(entry, 'filename'), text(entry, 'alt')))
    for raw in array(item, 'uploads', True):
        entry = Fields.parse(raw, '/uploads', ('asset_id', 'source_sha256', 'filename'))
        images = page.frame_locator('#editor-tistory_ifr').locator('body#tinymce img')
        matches = tuple(image for image in images.all() if image.get_attribute('data-filename') == text(entry, 'filename'))
        if len(matches) != 1:
            raise EditorCheckpointError('editor_resume_media_missing')
        source_url = matches[0].get_attribute('src') or ''
        if sha256(source_url.encode()).hexdigest() != identifier(entry, 'source_sha256', r'[0-9a-f]{64}'):
            raise EditorCheckpointError('editor_resume_media_identity')
        uploads.append(UploadedAsset(MediaId(identifier(entry, 'asset_id', r'[a-zA-Z0-9_-]+')),
                                    source_url, text(entry, 'filename')))
    if len(media) != 4 or len(uploads) != 4 or len({entry.source_url for entry in uploads}) != 4:
        raise EditorCheckpointError('editor_checkpoint_media')
    if not select_editor_mode(page, 'HTML', dry_run=False):
        raise EditorCheckpointError('editor_resume_source_unavailable')
    source = page.locator('#html-editor-container .CodeMirror textarea')
    source.press('ControlOrMeta+A')
    template = text(item, 'template')
    compiled = compose_native_article(template, source.input_value(), tuple(media))
    if compiled is None or not select_editor_mode(page, '기본모드', dry_run=False):
        raise EditorCheckpointError('editor_resume_source_invalid')
    return OwnedEditor(text(item, 'title'), compiled,
                       identifier(item, 'body_digest', r'[0-9a-f]{64}'), tuple(media), tuple(uploads), template)
