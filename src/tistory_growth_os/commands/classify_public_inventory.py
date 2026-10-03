from __future__ import annotations

from pathlib import Path
import sys

from ..artifacts.layout import ArtifactWriteError, safe_output_root
from ..contracts.json_ast import JsonMember, JsonNumber, JsonObject, JsonString
from ..contracts.json_decode import JsonDecodeError, parse_json, parse_json_file
from ..contracts.registry import ContractRegistry
from ..inventory.classify import classify_inventory
from ..inventory.decode import InventoryInputError, decode_public_inventory
from ..inventory.serialize import inventory_json
from .args import PublicInventoryArgs
from .output import write_optional_json


def execute_public_inventory(args: PublicInventoryArgs) -> tuple[int, JsonObject]:
    root = args.root.resolve()
    try:
        value = (
            parse_json(sys.stdin.buffer.read())
            if args.input == "-"
            else parse_json_file(_input_path(root, args.input))
        )
        request = decode_public_inventory(value)
        result = inventory_json(request, classify_inventory(request))
        if ContractRegistry.load(root / "contracts").validate("public-blog-inventory", result):
            raise InventoryInputError("/result: output violates inventory schema")
        write_optional_json(root, args.output, result)
        return 0, result
    except (InventoryInputError, JsonDecodeError):
        return 2, JsonObject((
            JsonMember("status", JsonString("invalid")),
            JsonMember("result_code", JsonString("INVENTORY_INPUT_INVALID")),
            JsonMember("external_write_count", JsonNumber(0)),
        ))


def _input_path(root: Path, relative: str) -> Path:
    path = safe_output_root(root, relative)
    if not path.is_file():
        raise ArtifactWriteError(
            "INPUT_NOT_FOUND",
            "/input",
            "inventory input must be a regular file",
        )
    return path
