from pathlib import Path

import pytest

from tistory_growth_os.preparation.contracts import PreparationError
from tistory_growth_os.preparation.provider import StageRequest, StageResponse
from tistory_growth_os.preparation.storage import StageStore


def test_source_catalog_change_invalidates_cached_writing(tmp_path: Path) -> None:
    def provider(request: StageRequest) -> StageResponse:
        return StageResponse('{}', request.stage, ())

    store = StageStore(tmp_path, provider)
    _ = store.run(StageRequest('writing', 'same task', tmp_path, source_urls=('https://example.org/a',)))
    with pytest.raises(PreparationError, match='checkpoint_changed'):
        _ = store.run(StageRequest('writing', 'same task', tmp_path, source_urls=('https://example.org/b',)))


def test_writing_schema_only_allows_exact_researched_urls() -> None:
    from tistory_growth_os.preparation.source_schema import writing_schema
    from tistory_growth_os.contracts.json_decode import parse_json
    from tistory_growth_os.domain.common import Fields, as_object, strings
    urls = ('https://example.org/a', 'https://xn--example.org/guide')
    node = as_object(parse_json(writing_schema(urls)), '')
    for key in ('properties', 'sections', 'items', 'properties', 'source_urls', 'items'):
        node = as_object(Fields(node, '', ()).required(key), '')
    assert strings(Fields(node, '', ()), 'enum', True, r'https://\S+') == urls
