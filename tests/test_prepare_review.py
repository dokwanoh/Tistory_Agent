from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import shutil
from typing import Final

import pytest

from tests.review_support import synthetic_review, write_review
from tistory_growth_os.artifacts.review_contract import ReviewDigest
from tistory_growth_os.commands.cli import main
from tistory_growth_os.contracts.json_ast import JsonBoolean, JsonNumber, JsonObject, JsonString
from tistory_growth_os.contracts.json_decode import parse_json, parse_json_file


ROOT: Final = Path(__file__).resolve().parents[1]


def project(root: Path, fixture: str = "tests/fixtures/topic_supported.json") -> None:
    _ = shutil.copytree(ROOT / "contracts", root / "contracts",
                        ignore=shutil.ignore_patterns("reviews"))
    _ = shutil.copyfile(ROOT / fixture, root / "input.json")


@pytest.mark.parametrize("include_review", [False, True])
def test_project_starts_without_operational_reviews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, include_review: bool,
) -> None:
    # Given: a source repository may contain operational review data.
    source = tmp_path / "source"
    reviews = source / "contracts/reviews"
    reviews.mkdir(parents=True)
    _ = (source / "contracts/catalog.json").write_bytes(b"{}")
    _ = (source / "input.json").write_bytes(b"{}")
    if include_review:
        _ = (reviews / "operational.json").write_bytes(b"{}")
    monkeypatch.setattr("tests.test_prepare_review.ROOT", source)
    # When: the synthetic CLI test project is created.
    target = tmp_path / "target"
    project(target, "input.json")
    # Then: contracts remain available but operational reviews are isolated.
    assert (target / "contracts/catalog.json").read_bytes() == b"{}"
    assert not tuple((target / "contracts/reviews").glob("*.json"))
    assert (reviews / "operational.json").exists() is include_review


def test_candidate_is_inspectable_without_creating_approval(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: automatically eligible content has no separate review receipt.
    project(tmp_path)
    # When: the operator requests an inspection-only candidate from the CLI.
    code = main(("prepare-review", "--root", str(tmp_path), "--fixture", "input.json",
                 "--output", "output", "--dry-run"))
    captured = capsys.readouterr()
    # Then: exact candidate text is available, but no approval package or receipt exists.
    assert code == 0, captured.err
    response = parse_json(captured.out)
    assert isinstance(response, JsonObject)
    assert response.get("status") == JsonString("REVIEW_REQUIRED")
    assert response.get("external_write_count") == JsonNumber(0)
    candidate = parse_json_file(tmp_path / "output/review-candidate.json")
    assert isinstance(candidate, JsonObject)
    assert candidate.get("approval_eligible") == JsonBoolean(False)
    assert candidate.get("scope") == JsonString("inspection_only")
    files = candidate.get("candidate_files_utf8")
    assert isinstance(files, JsonObject)
    assert len(files.members) == 10
    assert isinstance(files.get("article.html"), JsonString)
    assert {item.name for item in (tmp_path / "output").iterdir()} == {"review-candidate.json"}
    assert not tuple((tmp_path / "contracts/reviews").glob("*.json"))


@pytest.mark.parametrize("case", [
    ("tests/fixtures/topic_unsupported_claim.json", "CLAIM_EVIDENCE_REQUIRED"),
    ("tests/fixtures/topic_malformed.json", "CONTRACT_INVALID"),
    ("tests/fixtures/topic_rights_pending.json", "POLICY_EVIDENCE_REQUIRED"),
])
def test_candidate_command_preserves_content_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: tuple[str, str],
) -> None:
    # Given: invalid or blocked content cannot be promoted by inspection.
    fixture, expected = case
    project(tmp_path, fixture)
    # When: the same preparation command is requested.
    code = main(("prepare-review", "--root", str(tmp_path), "--fixture", "input.json",
                 "--output", "output", "--dry-run"))
    captured = capsys.readouterr()
    response = parse_json(captured.err)
    assert isinstance(response, JsonObject)
    # Then: the existing block remains and only diagnostics are allowed.
    assert code == 2
    assert response.get("result_code") == JsonString(expected)
    assert not (tmp_path / "output/review-candidate.json").exists()
    assert not (tmp_path / "output/bundle").exists()


def test_reviewed_candidate_matches_every_approval_byte(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: an exported candidate has a separate synthetic test-only review.
    project(tmp_path)
    base = ("--root", str(tmp_path), "--fixture", "input.json", "--dry-run")
    assert main(("prepare-review", *base, "--output", "inspection")) == 0
    _ = capsys.readouterr()
    candidate = parse_json_file(tmp_path / "inspection/review-candidate.json")
    assert isinstance(candidate, JsonObject)
    digest = candidate.get("subject_sha256")
    files = candidate.get("candidate_files_utf8")
    assert isinstance(digest, JsonString)
    assert isinstance(files, JsonObject)
    subject = ReviewDigest(digest.value)
    _ = write_review(tmp_path, subject, synthetic_review(subject, datetime.now(timezone.utc)))
    # When: the normal approval writer processes the original input, not the envelope.
    code = main(("run", *base, "--output", "approved"))
    captured = capsys.readouterr()
    # Then: every actual bundle byte equals the exported review subject.
    assert code == 0, captured.err
    bundle = tmp_path / "approved/bundle"
    assert {item.name for item in bundle.iterdir()} == {item.key for item in files.members}
    for item in files.members:
        assert isinstance(item.value, JsonString)
        assert (bundle / item.key).read_bytes() == item.value.value.encode("utf-8")


def test_candidate_does_not_satisfy_required_review(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: an operator has prepared a candidate but nobody reviewed it.
    project(tmp_path)
    base = ("--root", str(tmp_path), "--fixture", "input.json", "--dry-run")
    assert main(("prepare-review", *base, "--output", "inspection")) == 0
    _ = capsys.readouterr()
    # When: normal packaging is requested without a receipt.
    code = main(("run", *base, "--output", "attempt"))
    response = parse_json(capsys.readouterr().err)
    assert isinstance(response, JsonObject)
    # Then: inspection does not grant approval.
    assert code == 2
    assert response.get("result_code") == JsonString("REVIEW_REQUIRED")
    assert not (tmp_path / "attempt/bundle").exists()


@pytest.mark.parametrize("output", ["output", "../escape", "linked"])
def test_candidate_preserves_existing_files_and_path_boundary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], output: str,
) -> None:
    # Given: existing inspection material and a symlink cannot become write targets.
    project(tmp_path)
    directory = tmp_path / "output"
    directory.mkdir()
    existing = directory / "review-candidate.json"
    _ = existing.write_bytes(b"previous inspection")
    (tmp_path / "linked").symlink_to(directory, target_is_directory=True)
    # When: preparation would overwrite or escape the valid path boundary.
    code = main(("prepare-review", "--root", str(tmp_path), "--fixture", "input.json",
                 "--output", output, "--dry-run"))
    response = parse_json(capsys.readouterr().err)
    assert isinstance(response, JsonObject)
    # Then: the write is rejected and old evidence is preserved.
    assert code == 2
    assert response.get("result_code") in (JsonString("OUTPUT_EXISTS"), JsonString("OUTPUT_PATH_INVALID"))
    assert existing.read_bytes() == b"previous inspection"


def test_candidate_requires_explicit_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    # Given: valid fixture data never implies execution authority.
    project(tmp_path)
    # When: the required dry-run switch is omitted.
    code = main(("prepare-review", "--root", str(tmp_path), "--fixture", "input.json", "--output", "output"))
    response = parse_json(capsys.readouterr().err)
    assert isinstance(response, JsonObject)
    # Then: usage is rejected before output is created.
    assert code == 2
    assert response.get("result_code") == JsonString("CLI_USAGE_INVALID")
    assert not (tmp_path / "output").exists()
