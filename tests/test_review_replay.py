from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import shutil
from typing import Final

import pytest

from tests.review_support import approve_fixture
from tistory_growth_os.artifacts import package_review as gate
from tistory_growth_os.artifacts.layout import ArtifactWriteError
from tistory_growth_os.artifacts.writer import write_approval_bundle
from tistory_growth_os.contracts.json_decode import parse_json_file
from tistory_growth_os.contracts.json_encode import encode_json_bytes
from tistory_growth_os.domain.content_request_decode import decode_offline_run_request
from tistory_growth_os.domain.results import PipelineReady
from tistory_growth_os.pipeline.evidence import parse_canonical_input_digest
from tistory_growth_os.pipeline.orchestrator import run_offline_pipeline
from tistory_growth_os.policy.models import GateOutcome, PolicyEvaluation


ROOT: Final = Path(__file__).resolve().parents[1]
NOW: Final = datetime.fromisoformat("2026-09-07T07:00:00+00:00")


def reviewed_result(root: Path) -> tuple[PipelineReady, bytes]:
    _ = shutil.copytree(ROOT / "contracts", root / "contracts")
    fixture = ROOT / "tests/fixtures/topic_supported.json"
    _ = approve_fixture(root, fixture, NOW)
    value = parse_json_file(fixture)
    canonical = encode_json_bytes(value)
    ready = run_offline_pipeline(root, decode_offline_run_request(value),
                                 parse_canonical_input_digest(sha256(canonical).hexdigest()))
    assert isinstance(ready, PipelineReady)
    return ready, canonical


def test_expired_review_cannot_replay_old_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a previously created package and a clock beyond its review expiry.
    ready, canonical = reviewed_result(tmp_path)
    monkeypatch.setattr(gate, "current_time", lambda: NOW)
    first = write_approval_bundle(tmp_path, "output", ready, canonical)
    before = {item.name: item.read_bytes() for item in first.bundle_path.iterdir()}
    monkeypatch.setattr(gate, "current_time", lambda: NOW + timedelta(hours=2))
    # When: the same canonical request is retried.
    with pytest.raises(ArtifactWriteError) as caught:
        _ = write_approval_bundle(tmp_path, "output", ready, canonical)
    # Then: expiry blocks replay without deleting or changing historical artifacts.
    assert caught.value.code == "REVIEW_EXPIRED"
    assert {item.name: item.read_bytes() for item in first.bundle_path.iterdir()} == before


@pytest.mark.parametrize("file_name", ["article.html", "quality-report.json", "unexpected.txt"])
def test_modified_stored_bundle_cannot_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, file_name: str,
) -> None:
    # Given: disk content no longer matches the reviewed package, despite its manifest ID.
    ready, canonical = reviewed_result(tmp_path)
    monkeypatch.setattr(gate, "current_time", lambda: NOW)
    first = write_approval_bundle(tmp_path, "output", ready, canonical)
    changed = first.bundle_path / file_name
    _ = changed.write_text("tampered synthetic test content")
    # When: a replay is requested.
    with pytest.raises(ArtifactWriteError) as caught:
        _ = write_approval_bundle(tmp_path, "output", ready, canonical)
    # Then: the old ID does not attest to the changed bytes; data is preserved.
    assert caught.value.code == "REVIEW_OUTPUT_CHANGED"
    assert changed.read_text() == "tampered synthetic test content"


@pytest.mark.parametrize("field", ["blocked_policy", "empty_policy", "html"])
def test_forged_policy_state_cannot_use_existing_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    # Given: a caller replaced policy results that the serialized package does not expose.
    ready, canonical = reviewed_result(tmp_path)
    monkeypatch.setattr(gate, "current_time", lambda: NOW)
    policy = PolicyEvaluation(tuple(replace(item, outcome=GateOutcome.BLOCK)
                                    for item in ready.policy_evaluation.outcomes))
    forged = replace(ready, policy_evaluation=policy)
    if field == "empty_policy":
        forged = replace(ready, policy_evaluation=PolicyEvaluation(()))
    elif field == "html":
        forged = replace(ready, article_html="<p>unreviewed replacement</p>")
    # When: the public writer receives the internally inconsistent result.
    with pytest.raises(ArtifactWriteError) as caught:
        _ = write_approval_bundle(tmp_path, "output", forged, canonical)
    # Then: a matching input/receipt cannot mask inconsistent policy evaluation.
    assert caught.value.code == "CONTRACT_INVALID"
    assert not (tmp_path / "output/bundle").exists()


@pytest.mark.parametrize("file_name", [
    "catalog.json", "owner-decisions.json", "policy-evidence.json",
])
def test_changed_catalog_bytes_require_new_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, file_name: str,
) -> None:
    ready, canonical = reviewed_result(tmp_path)
    monkeypatch.setattr(gate, "current_time", lambda: NOW)
    catalog = tmp_path / "contracts" / file_name
    _ = catalog.write_bytes(catalog.read_bytes() + b"\n")
    with pytest.raises(ArtifactWriteError) as caught:
        _ = write_approval_bundle(tmp_path, "output", ready, canonical)
    assert caught.value.code == "REVIEW_REQUIRED"
    assert not (tmp_path / "output/bundle").exists()


@pytest.mark.parametrize("text", [
    "티스토리 글 발행 전 품질 체크리스트",
    "티스토리 Open API 종료 안내",
    "티스토리 Open API는 2024년 2월 말 종료되었다.",
    "제목, 목차, 링크, 이미지 대체 텍스트가 편집기 전달물에서 깨지지 않는지 확인한다.",
])
def test_changed_input_cannot_reuse_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str,
) -> None:
    _, canonical = reviewed_result(tmp_path)
    monkeypatch.setattr(gate, "current_time", lambda: NOW)
    changed = canonical.replace(text.encode("utf-8"), (text + " 테스트 수정").encode("utf-8"))
    assert changed != canonical
    fixture = tmp_path / "changed.json"
    _ = fixture.write_bytes(changed)
    value = parse_json_file(fixture)
    normalized = encode_json_bytes(value)
    ready = run_offline_pipeline(tmp_path, decode_offline_run_request(value),
                                parse_canonical_input_digest(sha256(normalized).hexdigest()))
    assert isinstance(ready, PipelineReady)
    with pytest.raises(ArtifactWriteError) as caught:
        _ = write_approval_bundle(tmp_path, "output", ready, normalized)
    assert caught.value.code == "REVIEW_REQUIRED"
    assert not (tmp_path / "output/bundle").exists()
