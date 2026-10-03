from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_CATALOG = ROOT / "contracts" / "policy-evidence.json"
OWNER_CATALOG = ROOT / "contracts" / "owner-decisions.json"
CLAIM_IDS = tuple(f"CL-{number:03d}" for number in range(1, 14))
OWNER_DECISION_IDS = tuple(f"ODR-{number:03d}" for number in range(1, 8))


def _json_tool(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "json.tool", str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _policy_catalog_issues(text: str) -> tuple[str, ...]:
    issues: list[str] = []
    if '"source_url": ""' in text or '"source_url"' not in text:
        issues.append("POLICY_EVIDENCE_REQUIRED")
    if '"checked_at": ""' in text or '"checked_at": "2026-09-06"' not in text:
        issues.append("POLICY_EVIDENCE_REQUIRED")
    if '"claim_id": "CL-013"' in text and '"temporal_qualifier": ""' in text:
        issues.append("TEMPORAL_QUALIFIER_REQUIRED")
    return tuple(issues)


def test_policy_catalog_is_dated_complete_and_offline_safe() -> None:
    # Given: the checked-in policy and owner-decision catalogs.
    policy_result = _json_tool(POLICY_CATALOG)
    owner_result = _json_tool(OWNER_CATALOG)

    # When: their serialized contract is inspected without a runtime parser.
    policy_text = POLICY_CATALOG.read_text(encoding="utf-8")
    owner_text = OWNER_CATALOG.read_text(encoding="utf-8")

    # Then: every research claim is dated and every owner boundary is explicit.
    assert policy_result.returncode == 0, policy_result.stderr
    assert owner_result.returncode == 0, owner_result.stderr
    assert _policy_catalog_issues(policy_text) == ()
    for claim_id in CLAIM_IDS:
        assert f'"claim_id": "{claim_id}"' in policy_text
    for token in (
        '"source_authority": "official"',
        '"source_url": "https://',
        '"checked_at": "2026-09-06"',
        '"control":',
        '"confidence":',
        '"uncertainty":',
        '"offline_editor_ready_package"',
        '"browser_automation_deferred"',
        '"scaled_content_abuse"',
        '"experience_enriched_originality"',
        '"genuine_traffic"',
        '"anchor"',
        '"offerwall"',
        '"source_url": "https://support.google.com/adsense/answer/48182?hl=en"',
        '"ai_virtual_person_endorsement"',
        '"controller_unsettled"',
    ):
        assert token in policy_text
    for unsupported in (
        '"mobile_interstitial"',
        '"overlay_fixed"',
        '"click_inducement"',
        '"self_ad_interference"',
    ):
        assert unsupported not in policy_text
    for decision_id in OWNER_DECISION_IDS:
        assert f'"decision_id": "{decision_id}"' in owner_text
    assert owner_text.count('"decision_id": "ODR-') == 7
    assert owner_text.count('"status": "OWNER_DECISION_REQUIRED"') == 7
    for token in (
        '"default_safe_behavior":',
        '"changes_once_answered":',
        '"offline_fixture_allowed": true',
        '"external_write_allowed": false',
    ):
        assert token in owner_text


def test_policy_catalog_fails_closed_when_source_or_controller_qualifier_is_missing() -> None:
    # Given: a valid source/dated catalog and isolated incomplete variants.
    policy_text = POLICY_CATALOG.read_text(encoding="utf-8")
    missing_source = policy_text.replace(
        "https://notice.tistory.com/2664", "", 1
    )
    missing_qualifier = policy_text.replace(
        "controller must be re-verified before any live integration", "", 1
    )

    # When: required evidence and temporal-controller qualifications are checked.
    source_issues = _policy_catalog_issues(missing_source)
    qualifier_issues = _policy_catalog_issues(missing_qualifier)

    # Then: both incomplete variants fail closed with stable diagnostics.
    assert source_issues == ("POLICY_EVIDENCE_REQUIRED",)
    assert qualifier_issues == ("TEMPORAL_QUALIFIER_REQUIRED",)
