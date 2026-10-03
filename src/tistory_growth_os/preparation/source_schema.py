from pathlib import Path

from ..contracts.json_ast import JsonArray, JsonMember, JsonObject, JsonString
from ..contracts.json_decode import parse_json
from ..contracts.json_encode import encode_json
from ..domain.common import Fields, as_object


def writing_schema(urls: tuple[str, ...]) -> str:
    path = Path(__file__).resolve().parents[3] / 'contracts/preparation/writing.json'
    value = as_object(parse_json(path.read_text()), '')
    route = ('properties', 'sections', 'items', 'properties', 'source_urls', 'items')
    replacement = JsonObject((JsonMember('type', JsonString('string')),
        JsonMember('enum', JsonArray(tuple(JsonString(url) for url in urls)))))

    def bind(node: JsonObject, keys: tuple[str, ...]) -> JsonObject:
        if not keys:
            return replacement
        child = as_object(Fields(node, '', ()).required(keys[0]), '')
        return JsonObject(tuple(JsonMember(member.key,
            bind(child, keys[1:]) if member.key == keys[0] else member.value) for member in node.members))

    return encode_json(bind(value, route))
