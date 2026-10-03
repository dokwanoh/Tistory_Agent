import argparse
import fcntl
import json
from pathlib import Path
import re
import subprocess
import sys

from ..artifacts.layout import ArtifactWriteError, safe_output_root
from ..contracts.json_decode import JsonDecodeError
from ..research.__main__ import collect_live
from ..research.intake import IntakeError
from .contracts import PreparationError
from .package import write_immutable
from .provider import codex_provider
from .runner import PreparationRun, execute, utc_now
from .storage import history_snapshot, prior_research_leads
from .publication import PublicationGrant
from .enrichment import REWORK_NEEDED


class Arguments(argparse.Namespace):
    root: str = '.'
    run_id: str = ''
    execute: bool = False
    publish_grant: str = ''
    interactive_media: bool = False


def main() -> int:
    parser = argparse.ArgumentParser(description='Prepare one reviewed Tistory package; optionally hand off an explicitly authorized immediate publication.')
    _ = parser.add_argument('--root', default='.')
    _ = parser.add_argument('--run-id', required=True)
    _ = parser.add_argument('--execute', action='store_true', help='Run bounded existing-account research/writing/media/review')
    _ = parser.add_argument('--publish-grant', default='', help='Project-relative one-run owner publication grant; never removes STOP')
    _ = parser.add_argument('--interactive-media', action='store_true', help='Pause at writing scenes for native image-generation handoff')
    args = parser.parse_args(namespace=Arguments())
    root = Path(args.root).resolve()
    directory = safe_output_root(root, '.artifacts/preparation/' + args.run_id)
    try:
        if re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,60}', args.run_id) is None:
            raise PreparationError('invalid_run_id')
        if not args.execute:
            print(json.dumps({'state': 'dry_run', 'run_id': args.run_id,
                'workflow_version': 'editorial-simple-v1',
                'stages': ['discovery', 'originals', 'decision', 'writing', 'media', 'edit', 'technical'],
                'model_calls': 0, 'external_write_count': 0, 'publication_authorized': False}))
            return 0
        run = PreparationRun(root, directory, args.run_id, utc_now)
        grant = PublicationGrant.read(run, safe_output_root(root, args.publish_grant)) if args.publish_grant else None
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / 'run.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise PreparationError('run_locked') from None
            initial = directory / 'input.json'
            if not initial.exists():
                try:
                    feed = collect_live()
                    signals = feed.decode('utf-8')
                except (IntakeError, OSError, subprocess.TimeoutExpired, UnicodeError):
                    feed = b''
                    signals = 'Trend metrics unavailable (UNKNOWN); use readable original sources, not invented metrics.'
                write_immutable(directory / 'signals.rss', feed)
                write_immutable(initial, json.dumps({'workflow_version': 'editorial-simple-v1', 'run_id': args.run_id,
                    'cutoff': utc_now().isoformat(), 'signals': signals
                    + '\nPrior UNVERIFIED research leads (not approved evidence; re-open sources and '
                    + 'requalify all facts/timestamps, ignore previous check status):\n' + prior_research_leads(root),
                    'history': history_snapshot(root),
                    **({'media_mode': 'interactive'} if args.interactive_media else {})}, ensure_ascii=False).encode())
            package = execute(run, codex_provider)
            if grant is not None:
                return grant.publish(package)
            print(json.dumps({'state': 'local_package_reviewed', 'package': str(package),
                'publication_authorized': False, 'external_blog_write_count': 0}))
        return 0
    except (PreparationError, ArtifactWriteError, JsonDecodeError, OSError, ImportError,
            subprocess.TimeoutExpired, UnicodeError, ValueError) as error:
        reason = error.code if isinstance(error, PreparationError) else type(error).__name__
        if reason == 'interactive_media_required':
            pending = sorted(directory.glob('**/interactive-media.pending.json'))
            pending_path = pending[-1].relative_to(root).as_posix() if pending else None
            print(json.dumps({'state': 'pending_media', 'reason': reason, 'retry_safe': True,
                'operation_id': args.run_id, 'pending_manifest': pending_path,
                'next_action': 'invoke native image generation for the recorded scenes, write the exact handoff, then resume the same operation'}, ensure_ascii=False), file=sys.stderr)
            return 2
        state = 'needs_enrichment' if reason in REWORK_NEEDED or reason in (
            'editorial_budget_exhausted', 'editorial_source_budget_exhausted',
            'editorial_media_budget_exhausted', 'editorial_candidates_exhausted') else 'held'
        print(json.dumps({'state': state, 'reason': reason, 'retry_safe': False,
            'next_action': 'preserve checkpoints; remedy the recorded defect before fresh review'
            if state == 'needs_enrichment' else 'reconcile authority, runtime or checkpoint integrity',
            'publication_eligible': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
