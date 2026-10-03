from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
PACKAGE = SOURCE / "tistory_growth_os"
NAMESPACES = (
    "contracts",
    "domain",
    "policy",
    "pipeline",
    "rendering",
    "artifacts",
    "audit",
    "commands",
)
_FORBIDDEN_IMPORTS = frozenset(
    {
        "aiohttp",
        "http.client",
        "httpx",
        "jsonschema",
        "pydantic",
        "requests",
        "socket",
        "urllib.request",
    }
)


def test_project_layout_has_python_shell_and_namespaces() -> None:
    assert (ROOT / "pyproject.toml").is_file()
    assert (ROOT / ".gitignore").is_file()
    assert (PACKAGE / "__init__.py").is_file()
    assert (PACKAGE / "__main__.py").is_file()
    assert (PACKAGE / "commands" / "cli.py").is_file()
    for namespace in NAMESPACES:
        assert (PACKAGE / namespace / "__init__.py").is_file(), namespace


def test_help_is_local_and_does_not_expose_publishing() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(SOURCE)
    result = subprocess.run(
        [sys.executable, "-m", "tistory_growth_os", "--help"],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "TISTORY GROWTH OS" in result.stdout
    assert "publish" not in result.stdout.lower()


def test_tooling_configuration_is_strict_and_runtime_is_offline() -> None:
    pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pyproject_lines = tuple(line.strip() for line in pyproject_text.splitlines())
    assert "[tool.pytest.ini_options]" in pyproject_lines
    assert "[tool.basedpyright]" in pyproject_lines
    assert 'pythonVersion = "3.11"' in pyproject_lines
    assert 'typeCheckingMode = "all"' in pyproject_lines
    assert 'reportAny = "error"' in pyproject_lines
    assert 'reportExplicitAny = "error"' in pyproject_lines
    dependency_lines = tuple(
        line for line in pyproject_lines if line.startswith("dependencies =")
    )
    assert dependency_lines == ("dependencies = []",)

    imported = tuple(
        found
        for path in SOURCE.rglob("*.py")
        for found in _forbidden_imports_in_source(path.read_text(encoding="utf-8"))
        if not (path == PACKAGE / 'preparation/source_transport.py' and found == 'socket')
    )
    assert imported == ()


def test_import_scan_allows_literals_but_rejects_forbidden_imports() -> None:
    scanner_literals = 'blocked = {"requests", "socket", "urllib.request"}'

    assert _forbidden_imports_in_source(scanner_literals) == ()
    assert _forbidden_imports_in_source("import requests\n") == ("requests",)
    assert _forbidden_imports_in_source("from urllib import request\n") == (
        "urllib.request",
    )


def _forbidden_imports_in_source(source: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=aliases):
                candidates = tuple(alias.name for alias in aliases)
            case ast.ImportFrom(module=module, names=aliases) if module is not None:
                candidates = (module,) + tuple(
                    f"{module}.{alias.name}" for alias in aliases
                )
            case _:
                candidates = ()
        for candidate in candidates:
            for forbidden in _FORBIDDEN_IMPORTS:
                if candidate == forbidden or candidate.startswith(f"{forbidden}."):
                    found.add(forbidden)
    return tuple(sorted(found))
