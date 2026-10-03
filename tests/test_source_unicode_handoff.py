from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.shared_sources import SourceDocument
from tistory_growth_os.preparation.source_access import bind_detail_sources
from tistory_growth_os.preparation.v2_sources import documents_from


def test_source_handoff_preserves_decomposed_original_text() -> None:
    # Given: a captured original whose Unicode representation is not NFC.
    body = 'Cafe\u0301 official policy. ' * 20
    document = SourceDocument('https://example.org/policy',
        datetime(2026, 9, 24, tzinfo=timezone.utc).isoformat(), 'full_text', body,
        sha256(body.encode()).hexdigest(), 'a' * 64, ())
    envelope = json.dumps({'documents': [asdict(document)]})
    # When: the captured source crosses the editorial handoff.
    result = documents_from(envelope)
    # Then: exact original text and its digest survive.
    assert result == (document,)


def test_detail_binding_preserves_decomposed_original_text() -> None:
    # Given: the legacy detail handoff consumes the same captured document.
    body = 'Cafe\u0301 official policy. ' * 20
    document = SourceDocument('https://example.org/policy',
        datetime(2026, 9, 24, tzinfo=timezone.utc).isoformat(), 'full_text', body,
        sha256(body.encode()).hexdigest(), 'a' * 64, ())
    envelope = json.dumps({'documents': [asdict(document)]})
    raw = '{"sources":[{"url":"https://example.org/policy","access":"unavailable","checked_at":"UNKNOWN"}]}'
    # When: access metadata is bound to the unchanged original.
    result = bind_detail_sources(raw, envelope)
    # Then: the host-confirmed access is retained rather than falsely rejected.
    assert '"access":"full_text"' in result


def test_source_handoff_still_rejects_changed_body() -> None:
    # Given: original hash with different content.
    body = 'Cafe\u0301 official policy. ' * 20
    document = SourceDocument('https://example.org/policy',
        datetime(2026, 9, 24, tzinfo=timezone.utc).isoformat(), 'full_text', body + 'changed',
        sha256(body.encode()).hexdigest(), 'a' * 64, ())
    # When / Then: a real mismatch remains rejected.
    with pytest.raises(PreparationError, match='source_snapshot_changed'):
        _ = documents_from(json.dumps({'documents': [asdict(document)]}))
