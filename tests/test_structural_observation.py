from dataclasses import replace
from datetime import datetime
from hashlib import sha256

from tistory_growth_os.delivery.editor_body_fingerprint import article_body_digest
from tistory_growth_os.delivery.native_article_source import NativeAlt
from tistory_growth_os.delivery.playwright_editor_readback import EditorContentSnapshot, EditorImage, EditorTagsSnapshot
from tistory_growth_os.delivery.playwright_manager import ManagerPostSummary, ManagerVisibility
from tistory_growth_os.delivery.playwright_observation import UploadedAsset, structural_reservation_observation
from tistory_growth_os.delivery.playwright_publish_settings import PublishSettingsSnapshot
from tistory_growth_os.delivery.playwright_saved_reservation import SavedReservationSnapshot
from tistory_growth_os.domain.ids import MediaId, PostId


def test_versioned_observation_preserves_uploaded_asset_binding() -> None:
    stamp = datetime.fromisoformat('2030-01-01T19:00:00+09:00')
    identity = PostId('93')
    media = tuple(NativeAlt(f'{i}.jpg', f'설명 {i}') for i in range(4))
    html = '<p>원고</p>' + ''.join(f'<figure data-ke-type="image"><img src="https://cdn.test/{i}" data-filename="{i}.jpg" alt="설명 {i}"></figure>' for i in range(4))
    images = tuple(EditorImage(f'https://cdn.test/{i}', f'설명 {i}', f'{i}.jpg') for i in range(4))
    uploads = tuple(UploadedAsset(MediaId(str(i)), image.source_url, f'{i}.jpg') for i, image in enumerate(images))
    snapshot = SavedReservationSnapshot(
        ManagerPostSummary(identity, '[예약]제목', 'https://example.tistory.com/93', '생활정보', stamp, None, True),
        EditorContentSnapshot(identity, '제목', html, sha256(html.encode()).hexdigest(), images),
        EditorTagsSnapshot(identity, frozenset(('해안',))),
        PublishSettingsSnapshot(identity, '제목', ManagerVisibility.PUBLIC, '생활정보', None, '제목', stamp), 0)
    observed = structural_reservation_observation(snapshot, uploads, media, stamp)
    assert observed is not None
    assert observed.target.content.body_digest == article_body_digest(html, media)
    changed_upload = (replace(uploads[0], source_url='https://cdn.test/unreviewed'), *uploads[1:])
    assert structural_reservation_observation(snapshot, changed_upload, media, stamp) is None
    broken = replace(snapshot, content=replace(snapshot.content, body_html=html.replace('설명 0', '누락')))
    assert structural_reservation_observation(broken, uploads, media, stamp) is None
