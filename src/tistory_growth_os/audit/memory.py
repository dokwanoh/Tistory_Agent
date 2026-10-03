from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Final


STATES: Final = frozenset({"DONE", "NEXT", "IN_PROGRESS", "BLOCKED", "DEFERRED", "PAUSED", "EXCLUDED_BY_OWNER"})
OWNER_GUARDS: Final = {
    "screen-reader": "EXCLUDED_BY_OWNER",
    "lighthouse": "EXCLUDED_BY_OWNER",
    "external-ads": "EXCLUDED_BY_OWNER",
    "print": "EXCLUDED_BY_OWNER",
    "remote-image-pixels": "EXCLUDED_BY_OWNER",
    "daily-schedule": "PAUSED",
    "reservations": "PAUSED",
}
VIEWS: Final = ("STATUS.md", "PLAN.md", "BACKLOG.md")
START: Final = "<!-- work:start -->"
END: Final = "<!-- work:end -->"


@dataclass(frozen=True, slots=True)
class WorkItem:
    identity: str
    kind: str
    state: str
    title: str
    evidence: str


def read_work(root: Path) -> tuple[WorkItem, ...]:
    lines = (root / "contracts/current-work.tsv").read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "id\tkind\tstate\ttitle\tevidence":
        raise ValueError("registry header invalid")
    items: list[WorkItem] = []
    seen: set[str] = set()
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) != 5 or any(not cell.strip() or "|" in cell for cell in cells):
            raise ValueError("registry row must have five nonempty, table-safe fields")
        identity, kind, state, title, evidence = cells
        if identity in seen:
            raise ValueError(f"duplicate work ID: {identity}")
        seen.add(identity)
        if state not in STATES:
            raise ValueError(f"unknown state: {identity}")
        if kind not in {"task", "guard"}:
            raise ValueError(f"unknown kind: {identity}")
        path = root / evidence
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError(f"missing or outside-root evidence: {identity}")
        if state == "DONE" and evidence.startswith("docs/history/"):
            raise ValueError(f"historical evidence alone cannot prove current completion: {identity}")
        items.append(WorkItem(identity, kind, state, title, evidence))
    guards = {item.identity: item.state for item in items if item.kind == "guard"}
    if guards != OWNER_GUARDS:
        raise ValueError("owner guard mismatch; a new explicit owner decision is required")
    if not any(item.kind == "task" for item in items):
        raise ValueError("registry has no tasks")
    return tuple(items)


def render_view(items: tuple[WorkItem, ...], name: str) -> str:
    if name not in VIEWS:
        raise ValueError(f"unknown view: {name}")
    rows = ["| ID | State | Work / control | Evidence / entry condition |", "| --- | --- | --- | --- |"]
    for item in items:
        if name == "PLAN.md" and (item.kind != "task" or item.state not in {"NEXT", "IN_PROGRESS", "BLOCKED"}):
            continue
        if name == "BACKLOG.md" and (item.kind != "task" or item.state != "DEFERRED"):
            continue
        rows.append(f"| {item.identity} | {item.state} | {item.title} | `{item.evidence}` |")
    return "\n".join(rows)


def audit_memory(root: Path) -> tuple[str, ...]:
    try:
        items = read_work(root)
    except (OSError, UnicodeError, ValueError) as error:
        return (f"registry: {error}",)
    issues: list[str] = []
    for name in VIEWS:
        try:
            source = (root / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            issues.append(f"{name}: {error}")
            continue
        if source.count(START) != 1 or source.count(END) != 1 or source.index(START) >= source.index(END):
            issues.append(f"{name}: missing, duplicate or reversed managed block")
            continue
        actual = source.split(START, 1)[1].split(END, 1)[0]
        if actual != "\n" + render_view(items, name) + "\n":
            issues.append(f"{name}: stale work view; regenerate from current-work.tsv")
    return tuple(issues)


class Arguments(argparse.Namespace):
    root: Path = Path.cwd()
    view: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only current-memory consistency check; never publishes or rewrites files.")
    _ = parser.add_argument("--root", type=Path, default=Path.cwd())
    _ = parser.add_argument("--view", choices=VIEWS, help="Print a derived table for a document; no files are written")
    args = parser.parse_args(namespace=Arguments())
    root = args.root
    if args.view is not None:
        try:
            print(render_view(read_work(root), args.view))
        except (OSError, UnicodeError, ValueError) as error:
            print(f"FAIL: {error}")
            return 1
        return 0
    issues = audit_memory(root)
    print("\n".join(issues) if issues else "PASS: current work, owner guards and document views agree")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
