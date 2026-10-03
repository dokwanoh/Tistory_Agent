from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
from tests.review_support import approve_fixture

from tistory_growth_os.artifacts import writer as bundle_writer
from tistory_growth_os.artifacts.writer import (
    ArtifactWriteError,
    BundleWriteStatus,
    write_approval_bundle,
)
from tistory_growth_os.contracts.json_decode import parse_json_file
from tistory_growth_os.contracts.json_encode import encode_json_bytes
from tistory_growth_os.domain.content_request_decode import decode_offline_run_request
from tistory_growth_os.domain.results import PipelineReady
from tistory_growth_os.pipeline.evidence import parse_canonical_input_digest
from tistory_growth_os.pipeline.orchestrator import run_offline_pipeline


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BUNDLE_FILES = {
    "article-draft.json",
    "article.html",
    "audit.json",
    "checksums.json",
    "content-brief.json",
    "evidence.json",
    "metadata.json",
    "publish-manifest.json",
    "quality-report.json",
    "rollback.json",
}


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    _ = shutil.copytree(ROOT / "contracts", root / "contracts")
    _ = approve_fixture(root, ROOT / "tests/fixtures/topic_supported.json")
    return root


def _ready(fixture: str = "topic_supported.json") -> tuple[PipelineReady, bytes]:
    value = parse_json_file(ROOT / "tests" / "fixtures" / fixture)
    canonical = encode_json_bytes(value)
    request = decode_offline_run_request(value)
    digest = parse_canonical_input_digest(sha256(canonical).hexdigest())
    result = run_offline_pipeline(ROOT, request, digest)
    assert isinstance(result, PipelineReady)
    return result, canonical


def _bundle_bytes(bundle: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(bundle.iterdir())}


def test_ready_result_writes_exact_atomic_approval_bundle(tmp_path: Path) -> None:
    root = _project(tmp_path)
    ready, canonical = _ready()

    result = write_approval_bundle(root, "artifacts/run-1", ready, canonical)

    bundle = root / "artifacts" / "run-1" / "bundle"
    assert result.status is BundleWriteStatus.CREATED
    assert result.bundle_path == bundle
    assert {path.name for path in bundle.iterdir()} == EXPECTED_BUNDLE_FILES
    assert (root / "artifacts/run-1/audit.jsonl").is_file()
    manifest = json.loads((bundle / "publish-manifest.json").read_text("utf-8"))
    assert manifest["state"] == "ready_for_approval"
    assert manifest["publish_mode"] == "approval_required"
    assert manifest["external_write_count"] == 0
    assert "publish-manifest.json" not in {
        item["relative_path"] for item in manifest["artifacts"]
    }
    for item in manifest["artifacts"]:
        payload = (bundle / item["relative_path"]).read_bytes()
        assert item["byte_count"] == len(payload)
        assert item["sha256"] == sha256(payload).hexdigest()


def test_same_key_and_input_replays_without_rewriting_bundle(tmp_path: Path) -> None:
    root = _project(tmp_path)
    ready, canonical = _ready()
    first = write_approval_bundle(root, "artifacts/run-1", ready, canonical)
    before = _bundle_bytes(first.bundle_path)

    replay = write_approval_bundle(root, "artifacts/run-1", ready, canonical)

    assert replay.status is BundleWriteStatus.IDEMPOTENT_REPLAY
    assert _bundle_bytes(replay.bundle_path) == before
    events = tuple(
        json.loads(line)
        for line in (root / "artifacts/run-1/audit.jsonl").read_text("utf-8").splitlines()
    )
    assert [item["event"] for item in events] == [
        "bundle_created",
        "idempotent_replay",
    ]
    assert all(item["external_write_count"] == 0 for item in events)


def test_same_key_with_different_normalized_input_fails_closed(tmp_path: Path) -> None:
    root = _project(tmp_path)
    ready, canonical = _ready()
    _ = write_approval_bundle(root, "artifacts/run-1", ready, canonical)
    changed_request = replace(
        ready.request,
        topic=replace(ready.request.topic, title="다른 제목"),
    )
    changed_canonical = canonical.replace(
        "티스토리 글 발행 전 품질 체크리스트".encode(),
        "다른 제목".encode(),
    )
    changed_digest = parse_canonical_input_digest(sha256(changed_canonical).hexdigest())
    changed = run_offline_pipeline(ROOT, changed_request, changed_digest)
    assert isinstance(changed, PipelineReady)
    _ = (root / "changed.json").write_bytes(changed_canonical)
    _ = approve_fixture(root, root / "changed.json")

    with pytest.raises(ArtifactWriteError) as caught:
        _ = write_approval_bundle(
            root,
            "artifacts/run-1",
            changed,
            changed_canonical,
        )

    assert caught.value.code == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("relative", ("../escape", "/tmp/escape"))
def test_output_path_cannot_escape_project_root(
    tmp_path: Path,
    relative: str,
) -> None:
    root = _project(tmp_path)
    ready, canonical = _ready()

    with pytest.raises(ArtifactWriteError) as caught:
        _ = write_approval_bundle(root, relative, ready, canonical)

    assert caught.value.code == "OUTPUT_PATH_INVALID"


def test_output_path_rejects_existing_symlink_component(tmp_path: Path) -> None:
    root = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "artifacts").symlink_to(outside, target_is_directory=True)
    ready, canonical = _ready()

    with pytest.raises(ArtifactWriteError) as caught:
        _ = write_approval_bundle(root, "artifacts/run-1", ready, canonical)

    assert caught.value.code == "OUTPUT_PATH_INVALID"
    assert tuple(outside.iterdir()) == ()


def test_injected_atomic_replace_failure_leaves_no_bundle_or_staging(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _project(tmp_path)
    ready, canonical = _ready()

    def fail_replace(source: Path, destination: Path) -> None:
        _ = source, destination
        raise OSError("injected atomic replacement failure")

    monkeypatch.setattr(bundle_writer.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected atomic replacement failure"):
        _ = write_approval_bundle(root, "artifacts/run-1", ready, canonical)

    output = root / "artifacts/run-1"
    assert not (output / "bundle").exists()
    assert not (output / "audit.jsonl").exists()
    assert tuple(output.glob(".bundle-staging-*")) == ()
