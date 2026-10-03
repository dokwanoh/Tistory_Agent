from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tistory_growth_os.contracts.json_decode import parse_json
from tistory_growth_os.learning import advise
from tistory_growth_os.learning_snapshot import decode_snapshot


def observation() -> str:
    return json.dumps({
        "scope": "private_read_only_ui_observation", "source": "tistory",
        "surface": "https://example.tistory.com/manage/statistics/blog",
        "selected_calendar_day": "2026-09-25", "timezone": "Asia/Seoul",
        "header_updated_at_display": "2026-09-25 12:00",
        "detail_exact_update_time": None, "interval_complete": False,
        "table_truncated": True, "loading_completed": True,
        "detail_day_views": 20,
        "aggregate_channels": {"search": 5, "daum_search": 5, "direct": 10, "other_referral": 5},
        "visible_rows": [
            {"title": "합성 행사 안내", "views": 9, "created_date": "2026-09-24"},
            {"title": "합성 교통 안내", "views": 3, "created_date": "2026-09-25"},
        ],
        "limitations": ["synthetic partial day"], "production_applied": False,
    }, ensure_ascii=False)


def invoke(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tistory_growth_os.learning", str(path)],
        env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        text=True, capture_output=True, check=False,
    )


def test_descriptive_advisory_when_partial_unjoined_snapshot(tmp_path: Path) -> None:
    # Given: synthetic snapshot and a sentinel for write isolation.
    path = tmp_path / "observation.json"
    path.write_text(observation())
    before = path.read_bytes()
    # When
    result = invoke(path)
    # Then: no winner assertion and no mutation.
    assert result.returncode == 0, result.stderr
    assert '"status": "descriptive_only"' in result.stdout
    assert '"production_applied": false' in result.stdout
    assert '"comparison_eligible": false' in result.stdout
    assert "합성 행사 안내" in result.stdout
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("old,new", [
    ('"loading_completed": true', '"loading_completed": false'),
    ('"views": 9', '"views": -1'),
    ('"views": 9', '"views": true'),
    ('"views": 9', '"views": 21'),
    ('"created_date": "2026-09-24"', '"created_date": "2026-09-26"'),
    ('합성 교통 안내', '합성 행사 안내'),
    ('"source": "tistory"', '"source": "other"'),
    ('"production_applied": false', '"production_applied": true'),
])
def test_unavailable_when_snapshot_invalid(tmp_path: Path, old: str, new: str) -> None:
    # Given
    path = tmp_path / "invalid.json"
    path.write_text(observation().replace(old, new))
    # When
    result = invoke(path)
    # Then
    assert result.returncode == 2
    assert '"status": "unavailable"' in result.stdout
    assert "합성" not in result.stdout
    assert not result.stderr


def test_unavailable_when_file_missing(tmp_path: Path) -> None:
    # Given / When
    result = invoke(tmp_path / "absent.json")
    # Then
    assert result.returncode == 2
    assert '"status": "unavailable"' in result.stdout
    assert str(tmp_path) not in result.stdout


def test_unavailable_when_json_malformed(tmp_path: Path) -> None:
    # Given
    path = tmp_path / "broken.json"
    path.write_text('{"private":')
    # When
    result = invoke(path)
    # Then
    assert result.returncode == 2
    assert '"status": "unavailable"' in result.stdout
    assert "private" not in result.stdout


def test_tied_leads_when_counts_equal() -> None:
    # Given
    snapshot = decode_snapshot(parse_json(observation().replace('"views": 3', '"views": 9')))
    # When
    result = advise(snapshot, "synthetic")
    # Then
    assert result["observed_lead_titles"] == ["합성 행사 안내", "합성 교통 안내"]
    assert result["comparison_eligible"] is False


def test_no_lead_when_observed_counts_zero() -> None:
    # Given
    snapshot = decode_snapshot(parse_json(observation().replace('"views": 9', '"views": 0').replace('"views": 3', '"views": 0')))
    # When
    result = advise(snapshot, "synthetic")
    # Then
    assert result["observed_lead_titles"] == []


def test_unjoined_calendar_days_remain_incomparable_when_complete() -> None:
    # Given
    snapshot = decode_snapshot(parse_json(observation().replace('"interval_complete": false', '"interval_complete": true')))
    # When
    result = advise(snapshot, "synthetic")
    # Then
    assert result["comparison_eligible"] is False
    assert "post_ids_unjoined" in result["limitations"]


def test_production_modules_remain_disconnected() -> None:
    # Given
    source = Path("src/tistory_growth_os")
    # When
    references = [path for path in source.rglob("*.py")
                  if path.name not in {"learning.py", "learning_snapshot.py", "learning_catalog.py"}
                  and ("import learning" in path.read_text() or "from .learning" in path.read_text()
                       or "from tistory_growth_os.learning" in path.read_text())]
    # Then
    assert references == []
