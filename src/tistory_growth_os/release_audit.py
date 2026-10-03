from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import Final


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    rule: str


PATTERNS: Final = (
    ('home_directory', re.compile(r'(?:/Users/|/home/|C:\\Users\\)[\w.-]+[/\\]')),
    ('advertising_id', re.compile(r'\b(?:ca-)?pub-\d{10,}\b|\bG-[A-Z0-9]{8,}\b')),
    ('email', re.compile(r'(?<![:\w])\b[\w.+-]+@(?!example\.(?:com|test|org)\b)[\w.-]+\.[a-z]{2,}\b')),
    ('private_key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('access_token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b')),
)
SAFE_HOSTS: Final = frozenset(('example', 'notice', 'www', 'other', 'fresh-blog'))
PRIVATE_ROOTS: Final = frozenset(('.local', '.artifacts', '.omo', 'content', 'browser-profile'))


def scan_bytes(path: str, data: bytes, private_terms: tuple[str, ...]) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    parts = Path(path).parts
    if (parts and parts[0] in PRIVATE_ROOTS) or Path(path).name in (
        '.env', 'auth.json', 'cookies.json', 'storage-state.json', 'storageState.json',
    ):
        findings.append(Finding(path, 'private_path'))
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return (*findings, Finding(path, 'binary_requires_review'))
    for rule, pattern in PATTERNS:
        if pattern.search(text):
            findings.append(Finding(path, rule))
    if any(hit.group(1) not in SAFE_HOSTS for hit in re.finditer(r'\b([a-z0-9-]+)\.tistory\.com\b', text)):
        findings.append(Finding(path, 'blog_identity'))
    if any(term.casefold() in text.casefold() for term in private_terms if term):
        findings.append(Finding(path, 'private_term'))
    return tuple(findings)


def scan_repository(root: Path, private_terms: tuple[str, ...]) -> tuple[Finding, ...]:
    result = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                            cwd=root, capture_output=True, check=True)
    findings: list[Finding] = []
    index = subprocess.run(['git', 'ls-files', '--stage', '-z'], cwd=root, capture_output=True, check=True)
    for entry in index.stdout.decode().split('\0'):
        if not entry:
            continue
        metadata, name = entry.split('\t', 1)
        mode, digest, _stage = metadata.split()
        if mode != '100644' and mode != '100755':
            findings.append(Finding(name, 'nonregular_index_entry'))
            continue
        blob = subprocess.run(['git', 'cat-file', 'blob', digest], cwd=root, capture_output=True, check=True)
        findings.extend(scan_bytes(name, blob.stdout, private_terms))
    for name in sorted(set(result.stdout.decode().split('\0')) - {''}):
        path = root / name
        if path.is_symlink():
            findings.append(Finding(name, 'symlink_requires_review'))
        elif path.is_file():
            findings.extend(scan_bytes(name, path.read_bytes(), private_terms))
    return tuple(sorted(set(findings), key=lambda finding: (finding.path, finding.rule)))


def main() -> int:
    terms = tuple(os.environ.get('TISTORY_PRIVATE_TERMS', '').split(','))
    findings = scan_repository(Path.cwd(), terms)
    for finding in findings:
        print(f'{finding.path}: {finding.rule}')
    print(f'release_content_findings={len(findings)}')
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
