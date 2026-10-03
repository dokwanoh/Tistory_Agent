"""Read-only checkpoint inventory, never a retry or publication authority."""

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Final

from ..artifacts.layout import ArtifactWriteError, safe_output_root
from ..contracts.json_decode import JsonDecodeError, parse_json
from ..domain.common import Fields, as_object, text


STAGES: Final = ('research', 'selection', 'evidence', 'writing', 'text_review', 'media', 'review')
LIMIT: Final = 2_000_000


@dataclass(frozen=True, slots=True)
class StageStatus:
    stage: str
    state: str
    action: str


@dataclass(frozen=True, slots=True)
class RunStatus:
    state: str
    stages: tuple[StageStatus, ...] = ()
    retry_safe: bool = False
    publication_state: str = 'not_checked'


def read_checkpoint(directory: Path, filename: str) -> str:
    path = safe_output_root(directory, filename)
    if path.stat().st_size > LIMIT:
        raise ArtifactWriteError('CHECKPOINT_OVERSIZED', '', 'checkpoint exceeds read limit')
    return path.read_text(encoding='utf-8')


def inspect_stage(directory: Path, stage: str, label: str) -> StageStatus:
    try:
        receipt = safe_output_root(directory, f'{stage}.receipt.json')
        response = safe_output_root(directory, f'{stage}.json')
        attempt = safe_output_root(directory, f'{stage}.attempt')
        if receipt.exists():
            value = as_object(parse_json(read_checkpoint(directory, receipt.name)), '')
            keys = ('request_sha256', 'response_sha256', 'session_id', 'tool_kinds')
            if value.get('sources_sha256') is not None:
                keys += ('sources_sha256',)
            fields = Fields.parse(value, '', keys)
            raw = read_checkpoint(directory, response.name)
            _ = parse_json(raw)
            request_digest = text(fields, 'request_sha256')
            response_digest = text(fields, 'response_sha256')
            valid = (re.fullmatch('[0-9a-f]{64}', request_digest) is not None
                     and response_digest == sha256(raw.encode()).hexdigest())
            if attempt.exists():
                valid = valid and read_checkpoint(directory, attempt.name) == request_digest
            if value.get('sources_sha256') is not None:
                valid = valid and text(fields, 'sources_sha256') == sha256(
                    read_checkpoint(directory, f'{stage}.sources.json').encode()).hexdigest()
            if valid:
                return StageStatus(label, 'response_recorded',
                                   'response integrity only; executor must revalidate quality and freshness')
            return StageStatus(label, 'checkpoint_invalid', 'preserve evidence; reconcile before execution')
        if attempt.exists() or response.exists():
            return StageStatus(label, 'attempt_unresolved',
                               'may be running or interrupted; reconcile process and evidence; do not clear attempt')
        return StageStatus(label, 'not_recorded', 'no completed checkpoint; do not infer retry authority')
    except (OSError, UnicodeError, JsonDecodeError, ArtifactWriteError):
        return StageStatus(label, 'checkpoint_invalid', 'preserve evidence; reconcile before execution')


def inspect_run(root: Path, run_id: str) -> RunStatus:
    if re.fullmatch('[a-z0-9][a-z0-9_-]{2,60}', run_id) is None:
        return RunStatus('invalid')
    try:
        directory = safe_output_root(root, f'.artifacts/preparation/{run_id}')
        if not directory.is_dir():
            return RunStatus('missing')
        stages = [inspect_stage(directory, stage, stage) for stage in STAGES]
        for subdir, names in (('research-expansion', ('research',)),
                              ('media-repair', ('media', 'review')),
                              ('media-repair/text-repair', ('writing', 'text_review', 'review')),
                              ('evidence-enrichment', ('evidence',)),
                              ('pre-media-repair', ('writing', 'text_review')),
                              ('pre-media-repair/pre-media-repair', ('writing', 'text_review')),
                              ('text-repair', ('writing', 'text_review', 'review'))):
            branch = safe_output_root(directory, subdir)
            if branch.is_dir():
                stages.extend(inspect_stage(branch, stage, f'{subdir}/{stage}') for stage in names)
                if subdir.startswith('pre-media-repair'):
                    if (branch / 'evidence.attempt').exists():
                        stages.append(inspect_stage(branch, 'evidence', f'{subdir}/evidence'))
                    extra = safe_output_root(branch, 'evidence-enrichment')
                    if extra.is_dir():
                        stages.append(inspect_stage(extra, 'evidence', f'{subdir}/evidence-enrichment/evidence'))
        return RunStatus('inspected', tuple(stages))
    except (OSError, ArtifactWriteError):
        return RunStatus('invalid')


class Arguments(argparse.Namespace):
    root: Path = Path.cwd()
    run_id: str = ''


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only preparation checkpoint diagnosis; no model, browser, retry or save.')
    _ = parser.add_argument('--root', type=Path, default=Path.cwd())
    _ = parser.add_argument('--run-id', required=True)
    args = parser.parse_args(namespace=Arguments())
    report = inspect_run(args.root, args.run_id)
    print(json.dumps(asdict(report), ensure_ascii=False))
    return 0 if report.state == 'inspected' else 1


if __name__ == '__main__':
    raise SystemExit(main())
