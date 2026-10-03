from pathlib import Path

from tistory_growth_os.delivery.native_checkpoint import append_checkpoint
from tistory_growth_os.delivery.playwright_observation import UploadedAsset
from tistory_growth_os.domain.ids import MediaId


def test_checkpoint_appends_without_exposing_signed_asset_urls(tmp_path: Path) -> None:
    path = tmp_path / 'checkpoint.jsonl'
    upload = UploadedAsset(MediaId('cover'), 'https://cdn.test/photo?secret=signed', 'cover.jpg')
    append_checkpoint(path, 'a' * 64, 'article_input/upload_verified', (upload,), False)
    append_checkpoint(path, 'a' * 64, 'held', (upload,), False)
    payload = path.read_text()
    records = payload.splitlines()
    assert len(records) == 2
    assert '"filenames": ["cover.jpg"]' in records[0]
    assert '"save_attempted": false' in records[1]
    assert 'signed' not in payload and 'cdn.test' not in payload
    assert path.stat().st_mode & 0o777 == 0o600
