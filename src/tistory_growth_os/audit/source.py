from __future__ import annotations

import ast
import io
import os
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .models import OfflineBoundaryReport, SourceHygieneReport


_FORBIDDEN_IMPORTS: Final = frozenset(
    {"aiohttp", "ftplib", "http.client", "httpx", "httpx2", "requests", "socket", "urllib.request", "urllib3", "websockets"}
)
_SKIP_DIRS: Final = frozenset({".artifacts", ".git", ".mypy_cache", ".omo", ".pytest_cache", ".ruff_cache", "__pycache__"})
_READ_ONLY_DNS_ADAPTER: Final = 'src/tistory_growth_os/preparation/source_transport.py'


@dataclass(frozen=True, slots=True)
class SourceAudit:
    hygiene: SourceHygieneReport
    boundary: OfflineBoundaryReport


@dataclass(frozen=True, slots=True)
class ImportSpec:
    name: str
    line: int


def audit_source(root: Path) -> SourceAudit:
    violations: list[str] = []
    oversized: list[str] = []
    external: set[str] = set()
    for path in _python_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative)
        except (OSError, UnicodeDecodeError, SyntaxError) as error:
            violations.append(f"{relative}:1:parse_error:{type(error).__name__}")
            continue
        if _pure_line_count(source) > 250:
            oversized.append(relative)
        file_violations, uses_network = _inspect_tree(tree, relative, source)
        violations.extend(file_violations)
        if uses_network or _adapter_filename(path) or _published_transition(tree):
            external.add(relative)
    return SourceAudit(
        SourceHygieneReport(tuple(sorted(violations)), tuple(sorted(oversized))),
        OfflineBoundaryReport(tuple(sorted(external))),
    )


def _python_files(root: Path) -> tuple[Path, ...]:
    source_root = root / "src"
    if not source_root.is_dir():
        return ()
    paths: list[Path] = []
    for directory, names, filenames in os.walk(source_root, followlinks=False):
        names[:] = [name for name in names if name not in _SKIP_DIRS and not Path(directory, name).is_symlink()]
        for filename in filenames:
            path = Path(directory, filename)
            if filename.endswith(".py") and _inside_root(path, root):
                paths.append(path)
    return tuple(sorted(paths))


def _inspect_tree(tree: ast.AST, relative: str, source: str) -> tuple[tuple[str, ...], bool]:
    violations: list[str] = []
    network = False
    for node in ast.walk(tree):
        for imported in _import_specs(node):
            if _forbidden_import(imported.name) and not (relative == _READ_ONLY_DNS_ADAPTER and imported.name == 'socket'):
                violations.append(f"{relative}:{imported.line}:forbidden_import:{imported.name}")
                network = True
        if isinstance(node, ast.arg) and _annotation_has_banned_name(node.annotation):
            violations.append(f"{relative}:{node.lineno}:banned_annotation")
        if isinstance(node, ast.AnnAssign) and _annotation_has_banned_name(node.annotation):
            violations.append(f"{relative}:{node.lineno}:banned_annotation")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _annotation_has_banned_name(node.returns):
            violations.append(f"{relative}:{node.lineno}:banned_annotation")
        if isinstance(node, ast.Call) and _call_name(node.func) == "cast":
            violations.append(f"{relative}:{node.lineno}:banned_cast")
        if isinstance(node, ast.Call) and _direct_json_load(node.func):
            violations.append(f"{relative}:{node.lineno}:direct_json_load")
        if isinstance(node, ast.ExceptHandler) and _broad_exception(node.type):
            violations.append(f"{relative}:{node.lineno}:broad_exception")
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and _ignore_comment(token.string):
            violations.append(f"{relative}:{token.start[0]}:type_ignore")
    return tuple(violations), network


def _import_specs(node: ast.AST) -> tuple[ImportSpec, ...]:
    match node:
        case ast.Import(names=aliases, lineno=line) if aliases:
            return tuple(ImportSpec(alias.name, line) for alias in aliases)
        case ast.ImportFrom(module=module, names=aliases, lineno=line) if module is not None:
            if module in {"http", "urllib"}:
                return tuple(ImportSpec(f"{module}.{alias.name}", line) for alias in aliases)
            return (ImportSpec(module, line),)
        case _:
            return ()


def _forbidden_import(name: str) -> bool:
    return any(name == forbidden or name.startswith(f"{forbidden}.") for forbidden in _FORBIDDEN_IMPORTS)


def _annotation_has_banned_name(annotation: ast.expr | None) -> bool:
    return annotation is not None and any(isinstance(node, ast.Name) and node.id in {"Any", "object"} for node in ast.walk(annotation))


def _call_name(function: ast.expr) -> str:
    match function:
        case ast.Name(id=name):
            return name
        case ast.Attribute(attr=name):
            return name
        case _:
            return ""


def _direct_json_load(function: ast.expr) -> bool:
    match function:
        case ast.Attribute(value=ast.Name(id="json"), attr=attribute):
            return attribute in {"load", "loads"}
        case _:
            return False


def _broad_exception(handler_type: ast.expr | None) -> bool:
    match handler_type:
        case ast.Name(id=name):
            return name in {"BaseException", "Exception"}
        case _:
            return False


def _published_transition(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "transition":
            if any(isinstance(child, ast.Constant) and child.value == "published" for child in ast.walk(node)):
                return True
        if isinstance(node, ast.ClassDef) and node.name == "PipelineState":
            if any(isinstance(child, ast.Constant) and child.value == "published" for child in ast.walk(node)):
                return True
    return False


def _ignore_comment(comment: str) -> bool:
    normalized = comment.lower().replace(" ", "")
    return normalized.startswith("#type:ignore") or normalized.startswith("#pyright:ignore")


def _adapter_filename(path: Path) -> bool:
    lowered = path.name.lower()
    return "publish" in lowered and "adapter" in lowered


def _pure_line_count(source: str) -> int:
    return sum(1 for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#"))


def _inside_root(path: Path, root: Path) -> bool:
    try:
        _ = path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True
