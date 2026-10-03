from contextlib import closing
from hashlib import sha256
from pathlib import Path

import pytest
from playwright.sync_api import Route, sync_playwright

from tistory_growth_os.delivery import playwright_html_input as writer
from tistory_growth_os.domain.ids import MediaId


@pytest.mark.parametrize('case', ['valid', 'pending', 'dry_run', 'wrong_digest', 'wrong_title', 'existing_post', 'existing_image'])
def test_upload_uses_file_chooser_once_for_verified_new_editor(case: str, tmp_path: Path) -> None:
    # Given: the native editor may insert a temporary blob before its upload completes.
    asset = tmp_path / 'cover.jpg'
    _ = asset.write_bytes(b'fixture-image-content')
    digest = sha256(asset.read_bytes()).hexdigest()
    existing = '<img data-filename="cover.jpg" src="https://cdn.example/old.jpg">' if case == 'existing_image' else ''
    receipt = ("i.src='blob:https://example.tistory.com/pending'; const name=this.files[0].name; "
               "setTimeout(()=>{i.src='https://cdn.example/new.jpg';i.dataset.filename=name},700);") if case == 'pending' else (
               "i.src='https://cdn.example/new.jpg'; i.dataset.filename=this.files[0].name;")
    html = f'''<textarea id="post-title-inp">검수된 시험 제목</textarea>
    <button aria-label="첨부" onclick="document.querySelector('[role=menuitem]').hidden=false">첨부</button>
    <button hidden role="menuitem" onclick="document.querySelector('input').click()">사진</button>
    <input type="file" hidden onchange="const i=document.createElement('img');
    {receipt}
    document.querySelector('iframe').contentDocument.body.appendChild(i)">
    <iframe id="editor-tistory_ifr" srcdoc='<body id="tinymce" contenteditable="true">{existing}</body>'></iframe>'''
    selections: list[str] = []

    def serve(route: Route) -> None:
        if 'cdn.example' in route.request.url:
            route.fulfill(status=204)
        else:
            route.fulfill(content_type='text/html; charset=utf-8', body=html)

    with sync_playwright() as p, closing(p.chromium.launch(channel='chrome', chromium_sandbox=True)) as browser:
        page = browser.new_page(service_workers='block')
        _ = page.route('**/*', serve)
        page.on('filechooser', lambda chooser: selections.append(str(chooser.is_multiple())))
        suffix = '/92' if case == 'existing_post' else ''
        _ = page.goto('https://example.tistory.com/manage/newpost' + suffix)
        request = writer.LocalUpload(MediaId('cover'), asset, '0' * 64 if case == 'wrong_digest' else digest,
                                     '다른 제목' if case == 'wrong_title' else '검수된 시험 제목')
        # When: one native file selection starts the upload.
        result = writer.upload_local_media(page, request, dry_run=case == 'dry_run')
        # Then: pending metadata must settle without a second file selection.
        if case in ('valid', 'pending'):
            assert result is not None
            assert result.asset_id == MediaId('cover')
            assert result.filename == 'cover.jpg'
            assert result.source_url == 'https://cdn.example/new.jpg'
            assert len(selections) == 1
        else:
            assert result is None
            assert selections == []
