from datetime import timedelta
from pathlib import Path

import pytest

from tests.preparation_fixture import NOW
from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.shared_sources import SourceReader


def test_collection_and_review_reuse_identical_body_and_check_time(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return ('<html><main><p>' + '공식 안내의 신청 조건과 일정입니다. ' * 30
                + '</p></main></html>').encode()

    reader = SourceReader(tmp_path, fetch, lambda: NOW)
    first = reader.read('https://example.org/guide')
    later = SourceReader(tmp_path, fetch, lambda: NOW + timedelta(hours=1))
    assert later.read(first.url) == first
    assert calls == [first.url]
    assert first.checked_at == NOW.isoformat()
    assert first.access == 'full_text'


def test_missing_body_is_unavailable_not_a_successful_read(tmp_path: Path) -> None:
    reader = SourceReader(tmp_path, lambda _: b'<html><body>Access denied</body></html>', lambda: NOW)
    result = reader.read('https://example.org/guide')
    assert result.access == 'unavailable'
    assert not result.body


def test_additional_source_uses_same_reader_without_refetching_original(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return ('<article>' + url + ' 실제 안내 본문. ' * 40 + '</article>').encode()

    reader = SourceReader(tmp_path, fetch, lambda: NOW)
    first = reader.read('https://example.org/notice')
    extra = reader.read('https://example.org/conditions')
    assert reader.read(first.url) == first
    assert extra.body != first.body
    assert len(calls) == 2


def test_unsafe_source_never_reaches_transport(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return b''

    reader = SourceReader(tmp_path, fetch, lambda: NOW)
    with pytest.raises(PreparationError, match='source_destination_denied'):
        _ = reader.read('https://example.org:30443/private')
    assert not calls


def test_changed_snapshot_is_not_silently_refetched(tmp_path: Path) -> None:
    reader = SourceReader(tmp_path, lambda _: ('<main>' + '공식 자료입니다. ' * 60 + '</main>').encode(), lambda: NOW)
    result = reader.read('https://example.org/guide')
    path = reader.path(result.url)
    _ = path.write_text(path.read_text().replace('공식', '변조'))
    with pytest.raises(PreparationError, match='source_snapshot_changed'):
        _ = reader.read(result.url)


def test_collection_time_cannot_be_changed_without_changing_body(tmp_path: Path) -> None:
    reader = SourceReader(tmp_path, lambda _: ('<main>' + '공식 자료입니다. ' * 60 + '</main>').encode(), lambda: NOW)
    result = reader.read('https://example.org/guide')
    path = reader.path(result.url)
    _ = path.write_text(path.read_text().replace(NOW.isoformat(), (NOW + timedelta(days=1)).isoformat()))
    with pytest.raises(PreparationError, match='source_snapshot_changed'):
        _ = reader.read(result.url)
