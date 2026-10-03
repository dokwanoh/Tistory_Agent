from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil
from typing import Final

import pytest

from tistory_growth_os.artifacts.layout import ArtifactWriteError
from tistory_growth_os.artifacts.writer import write_approval_bundle
from tistory_growth_os.contracts.json_decode import parse_json_file
from tistory_growth_os.contracts.json_encode import encode_json_bytes
from tistory_growth_os.domain.content_request_decode import decode_offline_run_request
from tistory_growth_os.domain.results import PipelineReady
from tistory_growth_os.pipeline.evidence import parse_canonical_input_digest
from tistory_growth_os.pipeline.orchestrator import run_offline_pipeline


ROOT: Final = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("relative_root", [False, True])
def test_unreviewed_ready_content_cannot_create_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative_root: bool,
) -> None:
    # Given: passing automated quality does not establish editorial approval.
    _ = shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    value = parse_json_file(ROOT / "tests/fixtures/topic_supported.json")
    canonical = encode_json_bytes(value)
    ready = run_offline_pipeline(tmp_path, decode_offline_run_request(value),
                                 parse_canonical_input_digest(sha256(canonical).hexdigest()))
    assert isinstance(ready, PipelineReady)
    monkeypatch.chdir(tmp_path)
    # When: the real writer is called without a separate review record.
    with pytest.raises(ArtifactWriteError) as caught:
        _ = write_approval_bundle(Path(".") if relative_root else tmp_path, "output", ready, canonical)
    # Then: it fails closed before either a manifest or bundle exists.
    assert caught.value.code == "REVIEW_REQUIRED"
    assert not (tmp_path / "output/bundle").exists()
    assert (tmp_path / "output/review-audit.jsonl").is_file()
