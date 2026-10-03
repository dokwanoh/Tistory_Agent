from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from datetime import datetime

import pytest

from tistory_growth_os.contracts.json_decode import parse_json_file
from tistory_growth_os.inventory.decode import (
    InventoryInputError,
    decode_public_inventory,
)
from tistory_growth_os.inventory.classify import classify_inventory
from tistory_growth_os.contracts.json_decode import parse_json


ROOT = Path(__file__).resolve().parents[1]


def test_inventory_rejects_observation_before_post_timestamp(tmp_path: Path) -> None:
    # Given
    source = ROOT / "tests/fixtures/public_inventory_input.json"
    changed = source.read_text(encoding="utf-8").replace(
        '"checked_date": "2026-09-07"',
        '"checked_date": "2019-01-01"',
    )
    fixture = tmp_path / "future-post.json"
    _ = fixture.write_text(changed, encoding="utf-8")

    # When / Then
    with pytest.raises(InventoryInputError):
        _ = decode_public_inventory(parse_json_file(fixture))


def test_recent_schedule_requires_review_instead_of_being_called_stale() -> None:
    request = decode_public_inventory(parse_json_file(ROOT / "tests/fixtures/public_inventory_input.json"))
    recent = replace(request.posts[0], published_at=datetime.fromisoformat("2026-09-01T12:00:00+09:00"), modified_at=datetime.fromisoformat("2026-09-01T12:00:00+09:00"), title="2026년 전시 일정")
    result = classify_inventory(replace(request, posts=(recent,)))[0]
    assert result.freshness_class.value == "review_required"


@pytest.mark.parametrize("origin", ["https://example:placeholder@example.tistory.com", "https://example.tistory.com?token=sample", "https://example.tistory.com#fragment"])
def test_origin_rejects_credentials_queries_and_fragments(origin: str) -> None:
    source = (ROOT / "tests/fixtures/public_inventory_input.json").read_text("utf-8")
    changed = source.replace('"https://example.tistory.com"', '"' + origin + '"')
    with pytest.raises(InventoryInputError):
        decode_public_inventory(parse_json(changed))


@pytest.mark.parametrize("stamp", ["20200907", "2026-09-08T00:00:00+09:00"])
def test_invalid_or_future_modified_timestamp_is_rejected(stamp: str) -> None:
    source = (ROOT / "tests/fixtures/public_inventory_input.json").read_text("utf-8")
    changed = source.replace('"modified_at": "2020-02-10T00:11:02+09:00"', '"modified_at": "' + stamp + '"')
    with pytest.raises(InventoryInputError):
        decode_public_inventory(parse_json(changed))
