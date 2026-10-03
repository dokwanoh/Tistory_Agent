from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Final

from tistory_growth_os.artifacts.layout import ArtifactWriteError
from tistory_growth_os.artifacts.writer import write_approval_bundle
from tistory_growth_os.artifacts.review_contract import ReviewDigest, ReviewSubject
from tistory_growth_os.contracts.json_ast import JsonMember, JsonObject, JsonString
from tistory_growth_os.contracts.json_decode import parse_json_file
from tistory_growth_os.contracts.json_encode import encode_json_bytes
from tistory_growth_os.domain.content_request_decode import decode_offline_run_request
from tistory_growth_os.domain.results import PipelineReady
from tistory_growth_os.pipeline.evidence import parse_canonical_input_digest
from tistory_growth_os.pipeline.orchestrator import run_offline_pipeline


ROOT: Final = Path(__file__).resolve().parents[1]


def synthetic_review(digest: ReviewDigest, now: datetime) -> JsonObject:
    pairs = (
        ("schema_version", "1.0.0"), ("scope", "local_package_only"),
        ("review_id", "review_synthetic_test"), ("reviewer_id", "synthetic_test_grader"),
        ("reviewer_kind", "independent_agent"), ("decision", "approved"),
        ("subject_sha256", digest), ("reviewed_at", (now - timedelta(minutes=1)).isoformat()),
        ("valid_until", (now + timedelta(hours=1)).isoformat()),
        ("evidence_valid_until", (now + timedelta(hours=2)).isoformat()),
        ("policy_valid_until", (now + timedelta(hours=3)).isoformat()),
    )
    return JsonObject(tuple(JsonMember(key, JsonString(value)) for key, value in pairs))


def write_review(root: Path, digest: ReviewDigest, value: JsonObject) -> Path:
    assert root.resolve() != ROOT
    directory = root / "contracts/reviews"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest}.json"
    _ = path.write_bytes(encode_json_bytes(value))
    return path


def approve_fixture(root: Path, fixture: Path, now: datetime | None = None) -> ReviewSubject:
    assert root.resolve() != ROOT
    value = parse_json_file(fixture)
    canonical = encode_json_bytes(value)
    ready = run_offline_pipeline(root, decode_offline_run_request(value),
                                 parse_canonical_input_digest(sha256(canonical).hexdigest()))
    assert isinstance(ready, PipelineReady)
    try:
        _ = write_approval_bundle(root, "_review_test_preflight", ready, canonical)
    except ArtifactWriteError as error:
        assert error.code == "REVIEW_REQUIRED"
        subject = ReviewSubject(ReviewDigest(error.message), max(item.checked_at for item in ready.evidence))
    else:
        raise AssertionError("synthetic review setup must start without approval")
    _ = write_review(root, subject.digest, synthetic_review(subject.digest, now or datetime.now(timezone.utc)))
    return subject
