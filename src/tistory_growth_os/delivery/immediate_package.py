from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

from ..artifacts.layout import safe_output_root
from ..artifacts.package_review import check_review, payload_digest
from ..artifacts.review_contract import ReviewCheck, ReviewCode, ReviewDigest, ReviewSubject
from ..contracts.json_decode import parse_json, parse_json_file
from ..domain.common import Fields, array, as_object, datetime_value, identifier, literal, strings, text
from ..domain.ids import MediaId
from ..domain.publishing_errors import PublishingInvariantError
from .editor_body_fingerprint import BODY_ALGORITHM, article_body_digest
from .immediate_execution import ImmediateIntent
from .native_article_source import NativeAlt
from .playwright_article_input import ImmediateArticleInput
from .playwright_html_input import LocalUpload
from .reservation_readback import ReservationContent, ReservationMedia


@dataclass(frozen=True, slots=True)
class ImmediatePackage:
    root: Path
    folder: Path
    article: ImmediateArticleInput = field(repr=False)
    evidence_checked_at: datetime

    def review(self, now: datetime) -> ReviewCheck:
        return check_review(self.root, ReviewSubject(ReviewDigest(self.article.intent.package_digest),
                                                     self.evidence_checked_at), now)


def load_immediate_package(root: Path, folder: Path, now: datetime) -> ImmediatePackage:
    relative = folder.absolute().relative_to(root.resolve()).as_posix()
    directory = safe_output_root(root, relative)
    payloads = {name: safe_output_root(directory, name).read_bytes()
                for name in ('manifest.json', 'article.html', 'evidence.md', 'quality.md')}
    if any(not body.strip() for body in payloads.values()):
        raise PublishingInvariantError('PACKAGE_EMPTY', '/artifacts', 'nonempty package artifacts required')
    raw = parse_json(payloads['manifest.json'].decode('utf-8'))
    version = text(Fields(as_object(raw, ''), '', ()), 'schema_version')
    owner_supplied = version == 'native-immediate-owner-v1'
    owner_keys = ('owner_topic_reference', 'owner_source_url') if owner_supplied else ()
    fields = Fields.parse(raw, '',
        ('schema_version', 'body_algorithm', 'title', 'operation_id', 'valid_until', 'event_at', 'selected_at',
         'evidence_checked_at', 'category', 'home_topic', 'tags', 'representative', 'media') + owner_keys)
    if version not in ('native-immediate-v1', 'native-immediate-v2', 'native-immediate-owner-v1'):
        raise PublishingInvariantError('PACKAGE_VERSION', '/schema_version', 'supported immediate package required')
    if owner_supplied:
        _ = identifier(fields, 'owner_topic_reference', r'owner-[a-zA-Z0-9_-]+')
        _ = identifier(fields, 'owner_source_url', r'https://[^\s]+')
    _ = literal(fields, 'body_algorithm', BODY_ALGORITHM)
    title = text(fields, 'title')
    expires = datetime_value(fields, 'valid_until')
    event = datetime_value(fields, 'event_at')
    selected = datetime_value(fields, 'selected_at')
    evidence = datetime_value(fields, 'evidence_checked_at')
    if (now.utcoffset() is None or not event <= selected <= evidence <= now < expires
            or (not owner_supplied and selected >= event + timedelta(hours=24))
            or expires > evidence + timedelta(hours=24)
            or (version == 'native-immediate-v1' and expires > event + timedelta(hours=24))):
        raise PublishingInvariantError('PACKAGE_EXPIRED', '/time', 'fresh selection, ordered timestamps and unexpired evidence required')
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
    digest = article_body_digest(template, alts)
    if digest is None:
        raise PublishingInvariantError('BODY_INVALID', '/article', 'valid article structure required')
    content = ReservationContent(title, digest, tuple(images), MediaId(text(fields, 'representative')),
        text(fields, 'category'), text(fields, 'home_topic'),
        tuple(sorted(strings(fields, 'tags', True, r'[^\s#][^\r\n]*'))))
    intent = ImmediateIntent(identifier(fields, 'operation_id', r'[a-zA-Z0-9_-]+'), content,
                             payload_digest(payloads), expires)
    article = ImmediateArticleInput(intent, template, tuple(uploads))
    if not article.valid():
        raise PublishingInvariantError('PACKAGE_INVALID', '/article', 'matching four media and body required')
    return ImmediatePackage(root.resolve(), directory, article, evidence)


@dataclass(frozen=True, slots=True)
class ImmediateAuthority:
    path: Path
    package: ImmediatePackage

    def __call__(self, request: ImmediateIntent, now: datetime) -> tuple[str, ...]:
        fields = Fields.parse(parse_json_file(self.path), '',
            ('scope', 'approval_id', 'operation_id', 'approved_at', 'package_digest', 'valid_until'))
        _ = literal(fields, 'scope', 'one-article-native-immediate')
        _ = identifier(fields, 'approval_id', r'[a-zA-Z0-9_-]+')
        operation = identifier(fields, 'operation_id', r'[a-zA-Z0-9_-]+')
        approved = datetime_value(fields, 'approved_at')
        digest = identifier(fields, 'package_digest', r'[0-9a-f]{64}')
        deadline = datetime_value(fields, 'valid_until')
        if (now.utcoffset() is None or request.operation_id != operation or request.package_digest != digest
                or not approved <= now < min(deadline, request.valid_until)):
            return ('immediate_scope_or_deadline',)
        current = load_immediate_package(self.package.root, self.package.folder, now)
        if current.article.intent != request:
            return ('package_changed',)
        reviewed = current.review(now)
        return () if reviewed.code is ReviewCode.APPROVED else (reviewed.code.value,)
