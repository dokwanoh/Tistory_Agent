from __future__ import annotations

from collections.abc import Sequence
import sys
from typing import assert_never

from ..artifacts.layout import ArtifactWriteError
from ..contracts.json_ast import JsonMember, JsonNumber, JsonObject, JsonString
from .args import (
    AuditArgs,
    CliUsageError,
    PublicInventoryArgs,
    ExtractAssetsArgs,
    RunArgs,
    PrepareReviewArgs,
    ValidateArgs,
    parse_command_args,
)
from .audit_project import audit_project_json
from .classify_public_inventory import execute_public_inventory
from .extract_public_assets import execute_asset_extraction
from .output import write_optional_json, write_stderr, write_stdout
from .run import execute_run
from .prepare_review import execute_prepare_review
from .validate_contracts import validate_contracts_json


_HELP = (
    "TISTORY GROWTH OS\n\n"
    "Local commands:\n"
    "  run --fixture PATH --output PATH --dry-run [--root PATH]\n"
    "  prepare-review --fixture PATH --output PATH --dry-run [--root PATH]\n"
    "  audit-project [--root PATH] [--json-out PATH]\n"
    "  validate-contracts [--root PATH] [--json-out PATH]\n"
    "  extract-public-assets --url URL < public-page.html\n"
    "  classify-public-inventory --input PATH|- --output PATH --dry-run "
    "[--root PATH]\n"
)


def _error_json(code: str, message: str) -> JsonObject:
    return JsonObject((
        JsonMember("status", JsonString("invalid")),
        JsonMember("result_code", JsonString(code)),
        JsonMember("message", JsonString(message)),
        JsonMember("external_write_count", JsonNumber(0)),
    ))


def main(argv: Sequence[str] | None = None) -> int:
    active = tuple(sys.argv[1:] if argv is None else argv)
    if active in (("--help",), ("-h",)):
        print(_HELP, end="")
        return 0
    try:
        command = parse_command_args(active)
        match command:
            case PrepareReviewArgs():
                exit_code, value = execute_prepare_review(command.run)
                if exit_code == 0:
                    write_stdout(value)
                else:
                    write_stderr(value)
                return exit_code
            case ExtractAssetsArgs():
                exit_code, value = execute_asset_extraction(command.url)
                if exit_code == 0:
                    write_stdout(value)
                else:
                    write_stderr(value)
                return exit_code
            case RunArgs():
                exit_code, value = execute_run(command)
                if exit_code == 0:
                    write_stdout(value)
                else:
                    write_stderr(value)
                return exit_code
            case AuditArgs():
                value = audit_project_json(command.root.resolve())
                write_optional_json(command.root.resolve(), command.json_out, value)
                write_stdout(value)
                status = value.get("status")
                return 0 if status == JsonString("pass") else 2
            case ValidateArgs():
                value = validate_contracts_json(command.root.resolve())
                write_optional_json(command.root.resolve(), command.json_out, value)
                write_stdout(value)
                return 0
            case PublicInventoryArgs():
                exit_code, value = execute_public_inventory(command)
                if exit_code == 0:
                    write_stdout(value)
                else:
                    write_stderr(value)
                return exit_code
            case _:
                assert_never(command)
    except (CliUsageError, ArtifactWriteError) as error:
        code = error.code if isinstance(error, ArtifactWriteError) else "CLI_USAGE_INVALID"
        write_stderr(_error_json(code, str(error)))
        return 2
    except (OSError, ValueError):
        write_stderr(_error_json("UNEXPECTED_ERROR", "unexpected local failure"))
        return 1
