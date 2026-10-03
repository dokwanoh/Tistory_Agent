from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

from ..artifacts.layout import safe_output_root
from ..artifacts.review_contract import ReviewCode
from ..contracts.json_decode import parse_json_file
from ..domain.common import Fields, datetime_value, identifier, literal
from .contracts import PreparationError
from .package import write_immutable
from .runner import PreparationRun


@dataclass(frozen=True, slots=True)
class PublicationGrant:
    run: PreparationRun
    path: Path
    approval_id: str
    approved_at: datetime
    valid_until: datetime

    @classmethod
    def read(cls, run: PreparationRun, path: Path) -> 'PublicationGrant':
        safe = safe_output_root(run.root, path.absolute().relative_to(run.root).as_posix())
        fields = Fields.parse(parse_json_file(safe), '',
            ('scope', 'approval_id', 'run_id', 'approved_at', 'valid_until'))
        _ = literal(fields, 'scope', 'one-preparation-native-immediate')
        identity = identifier(fields, 'run_id', r'[a-z0-9][a-z0-9_-]{2,60}')
        approved = datetime_value(fields, 'approved_at')
        deadline = datetime_value(fields, 'valid_until')
        if identity != run.run_id or not approved <= run.clock() < deadline:
            raise PreparationError('publication_grant_scope_or_deadline')
        if safe_output_root(run.root, '.artifacts/native-runtime/STOP').exists():
            raise PreparationError('kill_switch')
        return cls(run, safe, identifier(fields, 'approval_id', r'[a-zA-Z0-9_-]+'), approved, deadline)

    def bind(self, package_path: Path) -> Path:
        from ..delivery.immediate_package import ImmediateAuthority, load_immediate_package

        if PublicationGrant.read(self.run, self.path) != self:
            raise PreparationError('publication_grant_changed')
        package = load_immediate_package(self.run.root, package_path, self.run.clock())
        intent = package.article.intent
        if intent.operation_id != self.run.run_id or package.review(self.run.clock()).code is not ReviewCode.APPROVED:
            raise PreparationError('publication_exact_review_required')
        path = safe_output_root(self.run.directory, 'publication-authority.json')
        write_immutable(path, json.dumps({'scope': 'one-article-native-immediate',
            'approval_id': self.approval_id, 'operation_id': intent.operation_id,
            'approved_at': self.approved_at.isoformat(), 'package_digest': intent.package_digest,
            'valid_until': min(self.valid_until, intent.valid_until).isoformat()}, sort_keys=True).encode())
        if ImmediateAuthority(path, package)(intent, self.run.clock()):
            raise PreparationError('publication_authority_held')
        return path

    def publish(self, package_path: Path) -> int:
        authority = self.bind(package_path)
        print(json.dumps({'state': 'publication_handoff', 'operation_id': self.run.run_id}), flush=True)
        environment = dict(os.environ)
        environment['PYTHONPATH'] = os.pathsep.join(str(Path(entry).resolve()) for entry in sys.path if entry)
        result = subprocess.run([sys.executable, '-m', 'tistory_growth_os.delivery.immediate_runner',
            '--package', package_path.relative_to(self.run.root).as_posix(), '--execute',
            '--authority', authority.relative_to(self.run.root).as_posix()],
            cwd=self.run.root, env=environment, timeout=900, check=False)
        return 0 if result.returncode == 0 else 2
