from ..site_config import blog_host
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys
import sqlite3

from playwright.sync_api import Error as BrowserError, sync_playwright

from ..artifacts.layout import safe_output_root
from ..artifacts.review_contract import ReviewCode
from ..contracts.json_decode import JsonDecodeError
from .immediate_execution import ImmediateExecutor, ImmediateJournal
from .immediate_package import ImmediateAuthority, ImmediatePackage, load_immediate_package
from .native_checkpoint import append_checkpoint
from .native_runner import wait_manager_ready
from .playwright_immediate_surface import ImmediateNativeSurface
from .playwright_native_surface import NativePreparationError
from .playwright_observation import UploadedAsset
from .reservation_execution import ExecutionState
from .chrome_profile import ensure_publisher_profile


class Arguments(argparse.Namespace):
    package: str = ''
    execute: bool = False
    authority: str = ''
    recover: bool = False


def _execute(package: ImmediatePackage, authority: ImmediateAuthority, *, recover: bool) -> int:
    root = package.root
    stop = safe_output_root(root, '.artifacts/native-runtime/STOP')
    directory = safe_output_root(root, '.artifacts/native-runtime')
    directory.mkdir(parents=True, exist_ok=True)
    with safe_output_root(root, '.artifacts/native-runtime/worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if stop.exists():
            print(json.dumps({'state': 'blocked', 'reason': 'kill_switch'}))
            return 2
        journal = ImmediateJournal(safe_output_root(root, '.artifacts/native-runtime/save-intents.sqlite3'))
        intent = package.article.intent
        editor_path = safe_output_root(root, '.artifacts/native-runtime/editor-' + intent.package_digest + '.json')
        bindings = journal.media.read(intent.key, intent.package_digest) if recover else ()
        if recover and (len(bindings) != 4 or journal.saves.receipt(intent.key, intent.package_digest) is None):
            print(json.dumps({'state': 'held', 'reason': 'original_receipts_required',
                              'retry_safe': False, 'external_write_count': 0}))
            return 2
        profile = ensure_publisher_profile(root)
        with sync_playwright() as runtime:
            context = runtime.chromium.launch_persistent_context(
                str(profile), channel='chrome', headless=False,
                chromium_sandbox=True, accept_downloads=False, service_workers='block')
            try:
                editors = tuple(page for page in context.pages if '/manage/newpost' in page.url)
                resume_editor = bool(not recover and editor_path.exists() and journal.can_resume_editor(intent))
                if editors and (not resume_editor or len(editors) != 1):
                    raise NativePreparationError('existing_editor_requires_reconciliation')
                if resume_editor and not editors:
                    raise NativePreparationError('original_editor_required')
                page = editors[0] if resume_editor else (context.pages[0] if context.pages else context.new_page())
                page.set_default_timeout(5000)
                if not resume_editor:
                    _ = page.goto(f'https://{blog_host()}/manage/posts/', wait_until='domcontentloaded')
                    print(json.dumps({'state': 'manager_wait', 'login_recovery_seconds': 120,
                        'operation_id': intent.operation_id}), flush=True)
                    wait_manager_ready(page, timeout_ms=120000)
                anonymous_browser = runtime.chromium.launch(channel='chrome', headless=True, chromium_sandbox=True)
                try:
                    anonymous = anonymous_browser.new_context(accept_downloads=False, service_workers='block')
                    surface = ImmediateNativeSurface(page, anonymous, package.article, stop, authority)
                    surface.recovery_path = None if recover else editor_path
                    surface.bindings = bindings

                    def checkpoint(phase: str, uploads: tuple[UploadedAsset, ...]) -> None:
                        if (phase == 'article_input/input_verified'
                                and journal.media.read(intent.key, intent.package_digest) != surface.bindings):
                            journal.media.record(intent.key, intent.package_digest, surface.bindings)
                        append_checkpoint(safe_output_root(root, '.artifacts/native-runtime/checkpoints.jsonl'),
                            package.article.intent.package_digest, 'immediate/' + phase, uploads, surface.save_attempted)

                    surface.checkpoint = checkpoint
                    checkpoint('manager_ready', ())
                    try:
                        executor = ImmediateExecutor(journal, surface)
                        result = (executor.recover(intent) if recover
                                  else executor.run(intent, dry_run=False, resume_editor=resume_editor))
                    except (BrowserError, NativePreparationError, AssertionError):
                        checkpoint(surface.phase + '/held', surface.uploads)
                        raise
                    checkpoint(result.execution.state.value, surface.uploads)
                    print(json.dumps({'state': result.execution.state.value, 'reasons': result.execution.reasons,
                        'post_id': None if result.target is None else result.target.identity.post_id,
                        'operation_id': package.article.intent.operation_id, 'save_attempted': surface.save_attempted,
                        'remote_image_display': 'EXCLUDED_BY_OWNER'}))
                    return 0 if result.execution.state is ExecutionState.VERIFIED else 2
                finally:
                    anonymous_browser.close()
            finally:
                context.close()


def run(args: Arguments) -> int:
    root = Path.cwd().resolve()
    stop = safe_output_root(root, '.artifacts/native-runtime/STOP')
    if args.execute and stop.exists():
        print(json.dumps({'state': 'blocked', 'reason': 'kill_switch'}))
        return 2
    package = load_immediate_package(root, safe_output_root(root, args.package), datetime.now(timezone.utc))
    review = package.review(datetime.now(timezone.utc))
    if not args.execute:
        print(json.dumps({'state': 'dry_run', 'review': review.code.value,
            'package_digest': package.article.intent.package_digest,
            'operation_id': package.article.intent.operation_id,
            'browser_calls': 0, 'external_write_count': 0}))
        return 0 if review.code is ReviewCode.APPROVED else 2
    if not args.authority or review.code is not ReviewCode.APPROVED:
        print(json.dumps({'state': 'blocked', 'reason': 'authority_and_exact_review_required'}))
        return 2
    authority = ImmediateAuthority(safe_output_root(root, args.authority), package)
    reasons = authority(package.article.intent, datetime.now(timezone.utc))
    if reasons:
        print(json.dumps({'state': 'blocked', 'reasons': reasons}))
        return 2
    return _execute(package, authority, recover=args.recover)


def main() -> int:
    parser = argparse.ArgumentParser(description='One reviewed immediate-public article; default is no-browser dry-run.')
    _ = parser.add_argument('--package', required=True, help='Project-relative reviewed immediate package directory (v1/v2)')
    _ = parser.add_argument('--execute', action='store_true', help='Execute one separately authorized immediate article')
    _ = parser.add_argument('--authority', default='', help='Project-relative one-article immediate authority record')
    _ = parser.add_argument('--recover', action='store_true', help='Read-only receipt recovery; never retries an uncertain save')
    args = parser.parse_args(namespace=Arguments())
    try:
        return run(args)
    except (BrowserError, NativePreparationError, JsonDecodeError, OSError, sqlite3.Error, ValueError, AssertionError) as error:
        print(json.dumps({'state': 'held', 'error_type': type(error).__name__, 'retry_safe': False,
                          'reason': str(error),
                          'detail': 'Reconcile journal and native state; no automatic retry.'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
