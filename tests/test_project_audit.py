from __future__ import annotations

import shutil
from pathlib import Path

from tistory_growth_os.audit.project import audit_project


ROOT = Path(__file__).parents[1]


def test_runtime_browser_and_packages_are_not_repository_secret_inputs(tmp_path: Path) -> None:
    from tistory_growth_os.audit.secrets import audit_secrets

    for name in ("browser-profile", ".venv"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "runtime.txt").write_text("Bearer " + "a" * 24, encoding="utf-8")
    assert audit_secrets(tmp_path).matches == ()


def _copy_project(destination: Path) -> Path:
    root = destination / "project"
    _ = shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(".omo", ".artifacts", "__pycache__", ".pytest_cache", ".git", ".venv", "browser-profile"),
    )
    return root


def test_complete_project_passes_all_independent_sections() -> None:
    # Given: the complete checked-in offline project
    # When: the read-only project audit runs
    report = audit_project(ROOT)
    # Then: every independent section is clean
    assert report.status == "pass"
    assert report.required_documents.missing == ()
    assert report.traceability.missing == ()
    assert report.traceability.duplicates == ()
    assert report.contracts.issues == ()
    assert report.policy_evidence.missing == ()
    assert report.owner_decisions.issues == ()
    assert report.offline_boundary.external_adapters == ()
    assert report.source_hygiene.violations == ()
    assert report.source_hygiene.oversized_modules == ()
    assert report.secrets.matches == ()


def test_missing_required_document_fails_closed(tmp_path: Path) -> None:
    # Given: a project copy without a required memory document
    root = _copy_project(tmp_path)
    (root / "PROJECT_SPEC.md").unlink()
    # When: the audit runs
    report = audit_project(root)
    # Then: that exact document is missing and the audit fails
    assert report.status == "fail"
    assert report.required_documents.missing == ("PROJECT_SPEC.md",)


def test_duplicate_traceability_mapping_is_reported(tmp_path: Path) -> None:
    # Given: two mappings claim the same AS-IS identity
    root = _copy_project(tmp_path)
    path = root / "contracts/process-traceability.json"
    source = path.read_text(encoding="utf-8")
    _ = path.write_text(source.replace('"as_is_id": "ASIS-002"', '"as_is_id": "ASIS-001"', 1), encoding="utf-8")
    # When: the audit runs
    report = audit_project(root)
    # Then: duplicate and missing identities are both explicit
    assert report.traceability.duplicates == ("ASIS-001",)
    assert report.traceability.missing == ("ASIS-002",)


def test_missing_policy_source_and_date_are_reported(tmp_path: Path) -> None:
    # Given: one policy claim lacks source and checked date
    root = _copy_project(tmp_path)
    path = root / "contracts/policy-evidence.json"
    source = path.read_text(encoding="utf-8")
    source = source.replace('"source_url": "https://notice.tistory.com/2664"', '"source_url": ""', 1)
    source = source.replace('"checked_at": "2026-09-06"', '"checked_at": ""', 2)
    _ = path.write_text(source, encoding="utf-8")
    # When: the audit runs
    report = audit_project(root)
    # Then: the affected claim is missing evidence
    assert report.policy_evidence.missing == ("CL-001",)


def test_pending_owner_decisions_allow_offline_work() -> None:
    # Given: all seven owner decisions remain explicitly pending
    # When: the project audit runs
    report = audit_project(ROOT)
    # Then: pending decisions are accepted at the offline boundary
    assert report.owner_decisions.issues == ()


def test_required_document_symlink_cannot_escape_root(tmp_path: Path) -> None:
    # Given: a required document is replaced with an external symlink
    root = _copy_project(tmp_path)
    outside = tmp_path / "outside.md"
    _ = outside.write_text("external", encoding="utf-8")
    path = root / "PROJECT_SPEC.md"
    path.unlink()
    path.symlink_to(outside)
    # When: the audit runs
    report = audit_project(root)
    # Then: the escaping path is treated as missing
    assert report.required_documents.missing == ("PROJECT_SPEC.md",)


def test_secret_match_redacts_the_value(tmp_path: Path) -> None:
    # Given: a credential-shaped value in an ordinary text file
    root = _copy_project(tmp_path)
    secret = "AKIA" + "ABCDEFGHIJKLMNOP"
    _ = (root / "notes.txt").write_text(f"value={secret}\n", encoding="utf-8")
    # When: the audit runs
    report = audit_project(root)
    # Then: the match identifies the location without returning the secret
    match = next(item for item in report.secrets.matches if item.path == "notes.txt" and item.kind == "aws_access_key_id")
    assert match.kind == "aws_access_key_id"
    assert match.redacted == "<redacted>"
    assert secret not in repr(report)


def test_forbidden_network_import_is_reported(tmp_path: Path) -> None:
    # Given: source code imports an external network client
    root = _copy_project(tmp_path)
    path = root / "src/tistory_growth_os/network_probe.py"
    _ = path.write_text("import os, requests\n", encoding="utf-8")
    # When: the audit runs
    report = audit_project(root)
    # Then: the source hygiene and offline boundary identify it
    assert "src/tistory_growth_os/network_probe.py:1:forbidden_import:requests" in report.source_hygiene.violations
    assert report.offline_boundary.external_adapters == ("src/tistory_growth_os/network_probe.py",)


def test_oversized_python_module_is_reported(tmp_path: Path) -> None:
    # Given: a handwritten source module exceeds the 250-line ceiling
    root = _copy_project(tmp_path)
    path = root / "src/tistory_growth_os/oversized.py"
    _ = path.write_text("".join(f"value_{index} = {index}\n" for index in range(251)), encoding="utf-8")
    # When: the audit runs
    report = audit_project(root)
    # Then: the oversized module is named
    assert report.source_hygiene.oversized_modules == ("src/tistory_growth_os/oversized.py",)
