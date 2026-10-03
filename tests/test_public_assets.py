from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from tistory_growth_os.inventory.assets import public_reference


ROOT = Path(__file__).resolve().parents[1]
PAGE_URL = "https://example.tistory.com/entry/example"


def extract(html: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "tistory_growth_os", "extract-public-assets", "--url", PAGE_URL],
        input=html, capture_output=True, text=True, env=environment,
        check=False, timeout=15,
    )


def test_extracts_only_article_assets_and_redacts_query_values() -> None:
    html = '''<a href="https://outside.example/nav">navigation</a>
    <div class="contents_style"><div><a href="/entry/inside#part">inside</a></div>
    <img src="https://cdn.example/photo.jpg?signature=example-secret" alt="설명">
    <img src="/image.png"><img src="/decorative.png" alt="">
    <iframe src="https://video.example/embed/1"></iframe>출처: 예시</div>
    <a href="https://outside.example/footer">footer</a>'''
    result = extract(html)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["assets"]) == 5
    assert payload["image_count"] == 3
    assert payload["missing_alt_count"] == 1
    assert payload["empty_alt_count"] == 1
    assert payload["source_hint_present"] is True
    assert payload["external_write_count"] == 0
    assert "example-secret" not in result.stdout
    assert "outside.example" not in result.stdout
    assert payload["assets"][1]["query_redacted"] is True
    assert payload["assets"][0]["url"] == "https://example.tistory.com/entry/inside"


@pytest.mark.parametrize("html", ["<html>login</html>", '<div class="contents_style">unclosed'])
def test_missing_or_unclosed_body_fails_closed(html: str) -> None:
    result = extract(html)
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["result_code"] == "ASSET_EXTRACTION_INVALID"


def test_unsafe_schemes_and_private_targets_are_omitted() -> None:
    html = '''<div class="contents_style">
    <a href="javascript:alert(1)">x</a><img src="data:image/png;base64,example">
    <a href="http://127.0.0.1/">x</a><a href="https://localhost/">x</a>
    <a href="https://example:placeholder@host.example/">x</a>
    <a href="https://example.org/public">yes</a></div>'''
    result = extract(html)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert [item["url"] for item in payload["assets"]] == ["https://example.org/public"]
    assert payload["omitted_reference_count"] == 5


def test_percent_encoded_path_is_not_reinterpreted() -> None:
    url = "https://example.org/a%2Fb%3Fc"
    assert public_reference(url, PAGE_URL) == (url, "example.org", False)


def test_multiple_article_bodies_are_rejected() -> None:
    result = extract('<div class="contents_style"></div><div class="contents_style"></div>')
    assert result.returncode == 2
    assert result.stdout == ""


def test_image_occurrences_are_counted_separately_from_unique_urls() -> None:
    result = extract('<div class="contents_style"><img src="/same.png"/><img src="/same.png"/></div>')
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["image_count"] == 2
    assert len(payload["assets"]) == 2
    assert len({item["url"] for item in payload["assets"]}) == 1
