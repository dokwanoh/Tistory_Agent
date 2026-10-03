from dataclasses import dataclass
import re

from ..contracts.json_ast import JsonMember, JsonObject, JsonString
from ..contracts.json_decode import JsonDecodeError, parse_json
from ..contracts.json_encode import encode_json
from ..domain.common import as_object


@dataclass(frozen=True, slots=True)
class NativeAlt:
    filename: str
    alt: str


def compose_native_article(template: str, native_source: str, media: tuple[NativeAlt, ...]) -> str | None:
    if (len(media) != 4 or len({item.filename for item in media}) != 4
            or any(not item.filename.strip() or not item.alt.strip() for item in media)
            or '[##_Image' in template or '<img' in template.lower()):
        return None
    markers = tuple(f'{{{{MEDIA{n}}}}}' for n in range(1, 5))
    if any(template.count(marker) != 1 for marker in markers):
        return None
    if tuple(sorted(markers, key=template.index)) != markers:
        return None
    codes = tuple(match.group(1) for match in re.finditer(r'\[##_Image\|(.+?)_##\]', native_source, re.S))
    if len(codes) != 4:
        return None
    by_filename: dict[str, str] = {}
    for code in codes:
        pieces = code.split('|', 3)
        if len(pieces) != 4 or not all(pieces[:3]):
            return None
        try:
            metadata = as_object(parse_json(pieces[3]), '/image')
        except JsonDecodeError:
            return None
        matches = tuple(item for item in media if metadata.get('filename') == JsonString(item.filename))
        if len(matches) != 1 or matches[0].filename in by_filename:
            return None
        item = matches[0]
        updated = JsonObject(tuple(member for member in metadata.members if member.key != 'alt')
                             + (JsonMember('alt', JsonString(item.alt)),))
        by_filename[item.filename] = '[##_Image|' + '|'.join(pieces[:3]) + '|' + encode_json(updated).rstrip('\n') + '_##]'
    result = template
    for marker, item in zip(markers, media, strict=True):
        result = result.replace(marker, by_filename[item.filename])
    return result
