from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .models import SecretMatch, SecretsReport


_SKIP_DIRS: Final = frozenset({".artifacts", ".git", ".mypy_cache", ".omo", ".pytest_cache", ".ruff_cache", "__pycache__", ".venv", "browser-profile"})
_TEXT_SUFFIXES: Final = frozenset({"", ".css", ".html", ".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"})


@dataclass(frozen=True, slots=True)
class SecretPattern:
    kind: str
    pattern: re.Pattern[str]


_PATTERNS: Final = (
    SecretPattern("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    SecretPattern("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    SecretPattern("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)),
    SecretPattern(
        "api_token_assignment",
        re.compile(
            r"\b(?:api[_-]?(?:key|token)|access[_-]?token|auth[_-]?token|secret|password)\s*[:=]\s*[\"']?([^\s\"',;]{8,})",
            re.IGNORECASE,
        ),
    ),
    SecretPattern("url_userinfo", re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)),
)


def audit_secrets(root: Path) -> SecretsReport:
    matches: list[SecretMatch] = []
    for path in _repository_files(root):
        relative = path.relative_to(root).as_posix()
        forbidden = _forbidden_filename(path.name)
        if forbidden is not None:
            matches.append(SecretMatch(relative, 1, forbidden))
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(lines, start=1):
            for secret_pattern in _PATTERNS:
                found = secret_pattern.pattern.search(line)
                if found is not None and not _placeholder(found.group(0)):
                    matches.append(SecretMatch(relative, line_number, secret_pattern.kind))
    return SecretsReport(tuple(sorted(set(matches), key=lambda item: (item.path, item.line, item.kind))))


def _repository_files(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for directory, names, filenames in os.walk(root, followlinks=False):
        names[:] = [name for name in names if name not in _SKIP_DIRS and not Path(directory, name).is_symlink()]
        for filename in filenames:
            path = Path(directory, filename)
            if not path.is_symlink() and _inside_root(path, root):
                paths.append(path)
    return tuple(sorted(paths))


def _forbidden_filename(name: str) -> str | None:
    lowered = name.lower()
    if lowered == ".env":
        return "forbidden_filename_env"
    if lowered.endswith(".pem"):
        return "forbidden_filename_pem"
    if lowered.startswith("id_rsa"):
        return "forbidden_filename_private_key"
    if lowered.endswith(".json") and ("credential" in lowered or "service-account" in lowered):
        return "forbidden_filename_credentials"
    return None


def _placeholder(value: str) -> bool:
    lowered = value.lower()
    markers = ("unknown", "placeholder", "changeme", "example", "your_", "your-", "${", "<redacted>")
    return any(marker in lowered for marker in markers)


def _inside_root(path: Path, root: Path) -> bool:
    try:
        _ = path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True
