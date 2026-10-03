from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias, final


@final
class CliUsageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RunArgs:
    root: Path
    fixture: str
    output: str
    dry_run: bool


@dataclass(frozen=True, slots=True)
class PrepareReviewArgs:
    run: RunArgs


@dataclass(frozen=True, slots=True)
class AuditArgs:
    root: Path
    json_out: str | None


@dataclass(frozen=True, slots=True)
class ValidateArgs:
    root: Path
    json_out: str | None


@dataclass(frozen=True, slots=True)
class PublicInventoryArgs:
    root: Path
    input: str
    output: str
    dry_run: bool


@dataclass(frozen=True, slots=True)
class ExtractAssetsArgs:
    url: str


CommandArgs: TypeAlias = RunArgs | PrepareReviewArgs | AuditArgs | ValidateArgs | PublicInventoryArgs | ExtractAssetsArgs


def parse_command_args(argv: Sequence[str]) -> CommandArgs:
    if not argv:
        raise CliUsageError("a command is required")
    command = argv[0]
    match command:
        case "extract-public-assets":
            values, switches = _parse_flags(argv[1:], frozenset({"--url"}), frozenset())
            _reject_switches(switches)
            return ExtractAssetsArgs(_required(values, "--url"))
        case "run" | "prepare-review":
            values, switches = _parse_flags(
                argv[1:],
                frozenset({"--root", "--fixture", "--output"}),
                frozenset({"--dry-run"}),
            )
            fixture = _required(values, "--fixture")
            output = _required(values, "--output")
            if "--dry-run" not in switches:
                raise CliUsageError(f"{command} requires --dry-run")
            parsed = RunArgs(Path(values.get("--root", ".")), fixture, output, True)
            return PrepareReviewArgs(parsed) if command == "prepare-review" else parsed
        case "audit-project":
            values, switches = _parse_flags(
                argv[1:],
                frozenset({"--root", "--json-out"}),
                frozenset(),
            )
            _reject_switches(switches)
            return AuditArgs(
                Path(values.get("--root", ".")),
                values.get("--json-out"),
            )
        case "validate-contracts":
            values, switches = _parse_flags(
                argv[1:],
                frozenset({"--root", "--json-out"}),
                frozenset(),
            )
            _reject_switches(switches)
            return ValidateArgs(
                Path(values.get("--root", ".")),
                values.get("--json-out"),
            )
        case "classify-public-inventory":
            values, switches = _parse_flags(
                argv[1:],
                frozenset({"--root", "--input", "--output"}),
                frozenset({"--dry-run"}),
            )
            source = _required(values, "--input")
            output = _required(values, "--output")
            if "--dry-run" not in switches:
                raise CliUsageError("classify-public-inventory requires --dry-run")
            return PublicInventoryArgs(
                Path(values.get("--root", ".")),
                source,
                output,
                True,
            )
        case _:
            raise CliUsageError(f"unknown command: {command}")


def _parse_flags(
    tokens: Sequence[str],
    value_flags: frozenset[str],
    switch_flags: frozenset[str],
) -> tuple[dict[str, str], frozenset[str]]:
    values: dict[str, str] = {}
    switches: set[str] = set()
    index = 0
    while index < len(tokens):
        flag = tokens[index]
        if flag in switch_flags:
            if flag in switches:
                raise CliUsageError(f"duplicate flag: {flag}")
            switches.add(flag)
            index += 1
            continue
        if flag not in value_flags:
            raise CliUsageError(f"unknown flag: {flag}")
        if flag in values:
            raise CliUsageError(f"duplicate flag: {flag}")
        if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
            raise CliUsageError(f"missing value for {flag}")
        values[flag] = tokens[index + 1]
        index += 2
    return values, frozenset(switches)


def _required(values: dict[str, str], flag: str) -> str:
    value = values.get(flag)
    if value is None:
        raise CliUsageError(f"missing required flag: {flag}")
    return value


def _reject_switches(switches: frozenset[str]) -> None:
    if switches:
        raise CliUsageError("unexpected switch")
