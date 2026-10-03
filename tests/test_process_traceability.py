from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "contracts" / "process-traceability.json"
DOCUMENTS = tuple(ROOT / "docs" / f"{index:02d}_{name}.md" for index, name in (
    (1, "as_is"),
    (2, "bdw_analysis"),
    (3, "erask_transition"),
    (4, "to_be"),
    (5, "architecture"),
    (6, "tdd_and_evals"),
    (7, "security_policy_compliance"),
    (8, "delivery_roadmap"),
))
EXPECTED_AS_IS_IDS = tuple(f"ASIS-{index:03d}" for index in range(1, 13))
EXPECTED_TO_BE_IDS = tuple(f"TOBE-{index:03d}" for index in range(1, 13))
ERASK_CODES = frozenset(("E", "R", "A", "S", "K"))
ERASK_VOCABULARY = (
    ("E", "Erase"),
    ("R", "Replace"),
    ("A", "Assist"),
    ("S", "reStruct"),
    ("K", "Keep"),
    ("C", "Create"),
)


def _captures(field: str, text: str) -> tuple[str, ...]:
    return tuple(re.findall(rf'"{field}"\s*:\s*"([^"]+)"', text))


def _mapping_diagnostics(ids: tuple[str, ...]) -> tuple[str, ...]:
    counts = Counter(ids)
    missing = tuple(identifier for identifier in EXPECTED_AS_IS_IDS if counts[identifier] == 0)
    duplicate = tuple(sorted(identifier for identifier, count in counts.items() if count > 1))
    return tuple(f"missing:{identifier}" for identifier in missing) + tuple(
        f"duplicate:{identifier}" for identifier in duplicate
    )


def test_total_mapping_is_valid_and_one_to_one() -> None:
    # Given: the checked-in process traceability catalog.
    catalog_text = CATALOG.read_text(encoding="utf-8")

    # When: Python's JSON parser and the executable ID contract inspect it.
    result = subprocess.run(
        [sys.executable, "-m", "json.tool", str(CATALOG)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    as_is_ids = _captures("as_is_id", catalog_text)
    to_be_ids = _captures("to_be_id", catalog_text)
    erask_codes = _captures("primary_erask_code", catalog_text)
    erask_vocabulary = tuple(re.findall(
        r'"code"\s*:\s*"([ERASKC])"\s*,\s*"name"\s*:\s*"([^"]+)"',
        catalog_text,
    ))

    # Then: every provisional AS-IS block maps exactly once to one TO-BE block.
    assert result.returncode == 0, result.stderr
    assert _mapping_diagnostics(as_is_ids) == ()
    assert as_is_ids == EXPECTED_AS_IS_IDS
    assert to_be_ids == EXPECTED_TO_BE_IDS
    assert len(set(to_be_ids)) == len(to_be_ids)
    assert set(erask_codes) <= ERASK_CODES
    assert len(erask_codes) == len(EXPECTED_AS_IS_IDS)
    assert erask_vocabulary == ERASK_VOCABULARY


def test_duplicate_or_missing_mapping_is_rejected() -> None:
    # Given: isolated ID sequences with one missing and one duplicate mapping.
    missing_ids = EXPECTED_AS_IS_IDS[:-1]
    duplicate_ids = EXPECTED_AS_IS_IDS + (EXPECTED_AS_IS_IDS[0],)

    # When: deterministic mapping diagnostics inspect each sequence.
    missing_diagnostics = _mapping_diagnostics(missing_ids)
    duplicate_diagnostics = _mapping_diagnostics(duplicate_ids)

    # Then: the exact broken ID and defect class are reported.
    assert missing_diagnostics == ("missing:ASIS-012",)
    assert duplicate_diagnostics == ("duplicate:ASIS-001",)


def test_required_process_documents_are_nonempty_and_linked() -> None:
    # Given: the exact Phase 0/1 document paths required by the owner.
    texts = tuple(document.read_text(encoding="utf-8") for document in DOCUMENTS)

    # When: their machine-consumed identifiers are collected.
    joined = "\n".join(texts)

    # Then: all documents are substantive and all process IDs remain discoverable.
    assert all(len(text.strip()) >= 500 for text in texts)
    assert all(identifier in joined for identifier in EXPECTED_AS_IS_IDS)
    assert all(identifier in joined for identifier in EXPECTED_TO_BE_IDS)
    assert "OWNER_DECISION_REQUIRED" in joined
    assert "```mermaid" in texts[0]
    assert "```mermaid" in texts[3]
