from dataclasses import replace
from hashlib import sha256

from ..contracts.json_decode import parse_json
from ..domain.common import Fields, as_object, text
from .provider import StageRequest


def recorded_prompt(request: StageRequest, legacy: str) -> StageRequest:
    receipt = request.directory / f'{request.stage}.receipt.json'
    if receipt.exists():
        fields = Fields(as_object(parse_json(receipt.read_text()), ''), '', ())
        if text(fields, 'request_sha256') == sha256(legacy.encode()).hexdigest():
            return replace(request, prompt=legacy)
    return request
