from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_performance_advisory import observation


def catalog() -> str:
    return json.dumps({"schema_version": "publication-catalog-v1", "posts": [
        {"post_id": "1", "url": "https://example.tistory.com/1", "title": "합성 행사 안내",
         "created_date": "2026-09-24", "evidence_ref": "synthetic/receipt1"},
        {"post_id": "2", "url": "https://example.tistory.com/2", "title": "합성 교통 안내",
         "created_date": "2026-09-25", "evidence_ref": "synthetic/receipt2"},
    ]}, ensure_ascii=False)


def run_catalog(tmp_path: Path, content: str) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "snapshot.json"
    catalogue = tmp_path / "catalog.json"
    source.write_text(observation())
    catalogue.write_text(content)
    return subprocess.run(
        [sys.executable, "-m", "tistory_growth_os.learning", str(source), "--catalog", str(catalogue)],
        env={**os.environ, "PYTHONPATH": str(Path("src").resolve())},
        text=True, capture_output=True, check=False,
    )


def test_join_when_title_and_date_unique(tmp_path: Path) -> None:
    # Given
    content = catalog()
    # When
    result = run_catalog(tmp_path, content)
    # Then
    assert result.returncode == 0, result.stderr
    assert '"matched_rows": 2' in result.stdout
    assert '"catalog_sha256"' in result.stdout
    assert '"calendar_age_days": 1' in result.stdout
    assert '"calendar_age_days": 0' in result.stdout
    assert '"comparison_eligible": false' in result.stdout
    assert (tmp_path / "catalog.json").read_text() == content


@pytest.mark.parametrize("old,new", [
    ('합성 행사 안내', '다른 제목'),
    ('2026-09-24', '2026-09-23'),
])
def test_partial_join_when_title_or_date_mismatch(tmp_path: Path, old: str, new: str) -> None:
    # Given
    content = catalog().replace(old, new)
    # When
    result = run_catalog(tmp_path, content)
    # Then
    assert result.returncode == 0
    assert '"matched_rows": 1' in result.stdout
    assert '"post_id": null' in result.stdout


def test_ambiguous_when_duplicate_title_and_date(tmp_path: Path) -> None:
    # Given
    content = catalog().replace("합성 교통 안내", "합성 행사 안내").replace("2026-09-25", "2026-09-24")
    # When
    result = run_catalog(tmp_path, content)
    # Then
    assert result.returncode == 0
    assert '"matched_rows": 0' in result.stdout
    assert '"join_status": "ambiguous"' in result.stdout


@pytest.mark.parametrize("old,new", [
    ('"post_id": "2"', '"post_id": "1"'),
    ('https://example.tistory.com/1', 'https://other.tistory.com/1'),
    ('https://example.tistory.com/1', 'https://example.tistory.com/9'),
    ('synthetic/receipt1', ''),
])
def test_invalid_catalog_does_not_claim_join(tmp_path: Path, old: str, new: str) -> None:
    # Given
    content = catalog().replace(old, new)
    # When
    result = run_catalog(tmp_path, content)
    # Then
    assert result.returncode == 2
    assert '"status": "unavailable"' in result.stdout
    assert "합성" not in result.stdout
