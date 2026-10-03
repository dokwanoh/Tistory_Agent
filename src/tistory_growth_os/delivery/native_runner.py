from ..site_config import blog_host
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import sys

from playwright.sync_api import Error as BrowserError, Page, sync_playwright

from ..artifacts.layout import safe_output_root
from ..artifacts.review_contract import ReviewCode
from ..contracts.json_decode import JsonDecodeError
from .native_authority import PilotAuthority
from .native_checkpoint import append_checkpoint
from .native_package import load_native_package
from .new_reservation_execution import NewReservationExecutor
from .playwright_native_surface import NativePreparationError, NativeSurface
from .playwright_observation import UploadedAsset
from .reservation_execution import ExecutionState
from .reservation_readback import DailySlot
from .resume_journal import ResumeStage
from .save_intents import SaveIntentJournal


class Arguments(argparse.Namespace):
    package: str = ''
    execute: bool = False
    authority: str = ''
    resume: bool = False


def wait_manager_ready(page: Page, *, timeout_ms: int = 10000) -> None:
    page.get_by_role('heading', name='티스토리 관리센터 본문', exact=True).wait_for(state='attached', timeout=timeout_ms)
    page.locator('#mArticle input[id^="inpCheck"]').first.wait_for(state='attached', timeout=10000)


def run(args: Arguments) -> int:
    root = Path.cwd().resolve()
    stop_path = safe_output_root(root, '.artifacts/native-runtime/STOP')
    if args.execute and stop_path.exists():
        print(json.dumps({'state': 'blocked', 'reason': 'kill_switch'}))
        return 2
    folder = safe_output_root(root, args.package)
    now = datetime.now(timezone.utc)
    package = load_native_package(root, folder, now)
    review = package.review(now)
    if not args.execute:
        print(json.dumps({'state': 'dry_run', 'package_digest': package.article.intent.package_digest,
                          'review': review.code.value, 'scheduled_at': package.article.intent.scheduled_at.isoformat(),
                          'browser_calls': 0, 'external_write_count': 0}))
        return 0
    if not args.authority or review.code is not ReviewCode.APPROVED:
        print(json.dumps({'state': 'blocked', 'reason': 'authority_and_exact_review_required'}))
        return 2
    authority = PilotAuthority(safe_output_root(root, args.authority), package)
    denied = authority(package.article.intent, now)
    if denied:
        print(json.dumps({'state': 'blocked', 'reasons': denied}))
        return 2
    runtime_dir = safe_output_root(root, '.artifacts/native-runtime')
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if stop_path.exists():
        print(json.dumps({'state': 'blocked', 'reason': 'kill_switch'}))
        return 2
    with safe_output_root(root, '.artifacts/native-runtime/worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = SaveIntentJournal(safe_output_root(root, '.artifacts/native-runtime/save-intents.sqlite3'))
        point = journal.recovery.read(DailySlot(package.article.intent.scheduled_at).key,
                                      package.article.intent.package_digest) if args.resume else None
        if args.resume and (point is None or point.stage in (ResumeStage.INPUT_STARTED, ResumeStage.SAVE_STARTED)):
            print(json.dumps({'state': 'held', 'reason': 'read_only_reconciliation_required'}))
            return 2
        with sync_playwright() as runtime:
            context = runtime.chromium.launch_persistent_context(
                str(safe_output_root(root, 'browser-profile')), channel='chrome', headless=False,
                chromium_sandbox=True, accept_downloads=False, service_workers='block')
            try:
                editors = [tab for tab in context.pages if '/manage/newpost' in tab.url]
                retained = args.resume and point is not None and point.stage is ResumeStage.PREPARED
                if (retained and (len(editors) != 1 or editors[0].url.rstrip('/') != f'https://{blog_host()}/manage/newpost')):
                    raise NativePreparationError('retained_prepared_editor_required')
                if editors and not retained:
                    raise NativePreparationError('existing_editor_requires_reconciliation')
                page = editors[0] if retained else context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(5000)
                if not retained:
                    _ = page.goto(f'https://{blog_host()}/manage/posts/', wait_until='domcontentloaded')
                    wait_manager_ready(page)
                print(json.dumps({'phase': 'retained_editor' if retained else 'manager_ready'}), flush=True)
                surface = NativeSurface(page, package.article, stop_path.exists, authority, preserve_editor=retained)

                def checkpoint(phase: str, uploads: tuple[UploadedAsset, ...]) -> None:
                    append_checkpoint(safe_output_root(root, '.artifacts/native-runtime/checkpoints.jsonl'),
                                      package.article.intent.package_digest, phase, uploads, surface.save_attempted)

                surface.checkpoint = checkpoint
                checkpoint('manager_ready', ())
                try:
                    executor = NewReservationExecutor(journal, surface)
                    result = (executor.resume(package.article.intent, dry_run=False) if args.resume
                              else executor.run(package.article.intent, dry_run=False))
                except (BrowserError, NativePreparationError, AssertionError):
                    checkpoint(surface.phase + '/held', surface.uploads)
                    print(json.dumps({'phase': surface.phase, 'save_attempted': surface.save_attempted,
                                      'upload_receipt_count': len(surface.uploads)}), flush=True)
                    raise
                checkpoint(result.execution.state.value, surface.uploads)
                print(json.dumps({'state': result.execution.state.value,
                                  'reasons': result.execution.reasons,
                                  'post_id': None if result.target is None else result.target.post_id,
                                  'scheduled_at': package.article.intent.scheduled_at.isoformat()}))
                return 0 if result.execution.state is ExecutionState.VERIFIED else 2
            finally:
                context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='One-slot native reservation pilot; default is no-browser dry-run.')
    _ = parser.add_argument('--package', required=True, help='Project-relative reviewed package directory')
    _ = parser.add_argument('--execute', action='store_true', help='Execute only the separately authorized pilot')
    _ = parser.add_argument('--resume', action='store_true', help='Resume only proven pre-save state; never clear a claim')
    _ = parser.add_argument('--authority', default='', help='Project-relative owner pilot authority record')
    args = parser.parse_args(namespace=Arguments())
    try:
        return run(args)
    except (BrowserError, NativePreparationError, JsonDecodeError, OSError, ValueError, AssertionError) as error:
        print(json.dumps({'state': 'held', 'error_type': type(error).__name__,
                          'retry_safe': False, 'detail': 'Reconcile journal and native state; no automatic retry.'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
