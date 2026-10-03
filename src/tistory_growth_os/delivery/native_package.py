from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

from ..artifacts.layout import safe_output_root
from ..artifacts.package_review import check_review, payload_digest
from ..artifacts.review_contract import ReviewCheck, ReviewDigest, ReviewSubject
from ..contracts.json_decode import parse_json
from ..domain.common import Fields, array, datetime_value, identifier, literal, strings, text
from ..domain.ids import MediaId
from .editor_body_fingerprint import BODY_ALGORITHM, article_body_digest
from .native_article_source import NativeAlt
from .new_reservation_identity import NewReservationIntent
from .playwright_article_input import ArticleInput
from .playwright_html_input import LocalUpload
from .reservation_readback import ReservationContent, ReservationMedia


@dataclass(frozen=True, slots=True)
class NativePackage:
    root: Path
    folder: Path
    article: ArticleInput = field(repr=False)
    evidence_checked_at: datetime

    def review(self, now: datetime) -> ReviewCheck:
        return check_review(self.root, ReviewSubject(ReviewDigest(self.article.intent.package_digest),
                                                     self.evidence_checked_at), now)


def load_native_package(root: Path, folder: Path, now: datetime) -> NativePackage:
    relative = folder.absolute().relative_to(root.resolve()).as_posix()
    directory = safe_output_root(root, relative)
    payloads = {name: safe_output_root(directory, name).read_bytes()
                for name in ('manifest.json', 'article.html', 'evidence.md', 'quality.md')}
    if any(not body.strip() for body in payloads.values()):
        raise ValueError('empty_package_artifact')
    fields = Fields.parse(parse_json(payloads['manifest.json'].decode('utf-8')), '',
                          ('schema_version', 'body_algorithm', 'title', 'scheduled_at', 'event_at', 'selected_at',
                           'evidence_checked_at', 'category', 'home_topic', 'tags', 'representative', 'media'))
    _ = literal(fields, 'schema_version', 'native-reviewed-v1')
    _ = literal(fields, 'body_algorithm', BODY_ALGORITHM)
    title = text(fields, 'title')
    scheduled = datetime_value(fields, 'scheduled_at')
    event = datetime_value(fields, 'event_at')
    selected = datetime_value(fields, 'selected_at')
    evidence = datetime_value(fields, 'evidence_checked_at')
    if (now.utcoffset() is None or not event <= selected <= evidence <= now < scheduled
            or not timedelta(0) <= scheduled - event < timedelta(hours=24)):
        raise ValueError('freshness_or_time_boundary')
    uploads: list[LocalUpload] = []
    images: list[ReservationMedia] = []
    for index, value in enumerate(array(fields, 'media', True)):
        entry = Fields.parse(value, f'/media/{index}', ('asset_id', 'file', 'alt'))
        name = identifier(entry, 'file', r'(?:media/)?[a-zA-Z0-9_-]+\.(?:jpg|jpeg|png|webp)')
        path = safe_output_root(directory, name)
        payloads[name] = path.read_bytes()
        identity = MediaId(identifier(entry, 'asset_id', r'[a-zA-Z0-9_-]+'))
        images.append(ReservationMedia(identity, text(entry, 'alt')))
        uploads.append(LocalUpload(identity, path, sha256(payloads[name]).hexdigest(), title))
    template = payloads['article.html'].decode('utf-8')
    alts = tuple(NativeAlt(upload.path.name, image.alt) for upload, image in zip(uploads, images, strict=True))
    body_digest = article_body_digest(template, alts)
    if body_digest is None:
        raise ValueError('invalid_article_structure')
    content = ReservationContent(title, body_digest, tuple(images), MediaId(text(fields, 'representative')),
                                 text(fields, 'category'), text(fields, 'home_topic'),
                                 tuple(sorted(strings(fields, 'tags', True, r'[^\s#][^\r\n]*'))))
    intent = NewReservationIntent(scheduled, content, payload_digest(payloads))
    article = ArticleInput(intent, template, tuple(uploads))
    if not article.valid():
        raise ValueError('invalid_input_package')
    return NativePackage(root.resolve(), directory, article, evidence)
