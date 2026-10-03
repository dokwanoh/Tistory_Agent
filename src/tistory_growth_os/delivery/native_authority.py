from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..artifacts.review_contract import ReviewCode
from ..contracts.json_decode import parse_json_file
from ..domain.common import Fields, datetime_value, identifier, literal
from .native_package import NativePackage, load_native_package
from .new_reservation_identity import NewReservationIntent


@dataclass(frozen=True, slots=True)
class PilotAuthority:
    path: Path
    package: NativePackage

    def __call__(self, request: NewReservationIntent, now: datetime) -> tuple[str, ...]:
        fields = Fields.parse(parse_json_file(self.path), '',
                              ('scope', 'approval_id', 'scheduled_at', 'package_digest', 'valid_until'))
        _ = literal(fields, 'scope', 'one-slot-native-reservation')
        _ = literal(fields, 'approval_id', 'owner-20260920-independent-pilot')
        approved_at = datetime_value(fields, 'scheduled_at')
        digest = identifier(fields, 'package_digest', r'[0-9a-f]{64}')
        deadline = datetime_value(fields, 'valid_until')
        if (approved_at != datetime.fromisoformat('2026-09-20T19:00:00+09:00')
                or request.scheduled_at != approved_at or request.package_digest != digest
                or now >= min(deadline, approved_at)):
            return ('pilot_scope_or_deadline',)
        current = load_native_package(self.package.root, self.package.folder, now)
        if current.article.intent != request:
            return ('package_changed',)
        reviewed = current.review(now)
        return () if reviewed.code is ReviewCode.APPROVED else (reviewed.code.value,)
