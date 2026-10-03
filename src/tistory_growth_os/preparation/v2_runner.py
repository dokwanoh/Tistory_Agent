from hashlib import sha256
from pathlib import Path

from ..artifacts.layout import safe_output_root
from ..contracts.json_decode import parse_json
from ..contracts.json_encode import encode_json
from ..domain.common import Fields, as_object, datetime_value, text
from .contracts import PreparationError
from .editorial import CATEGORIES, TOPICS
from .package import write_immutable
from .provider import Provider, StageRequest
from .run_contract import PreparationRun
from .storage import StageStore
from .v2_editor import EditBudget, EditorialWork, edit_package
from .v2_sources import DiscoveryPool, SelectionContext, discover, select_sources
from . import prompts, v2_prompts


def execute_v2(run: PreparationRun, provider: Provider) -> Path:
    source = (run.directory / 'input.json').read_text()
    initial = as_object(parse_json(source), '')
    keys = ('workflow_version', 'run_id', 'cutoff', 'signals', 'history')
    if initial.get('media_mode') is not None:
        keys += ('media_mode',)
    fields = Fields.parse(initial, '', keys)
    if text(fields, 'run_id') != run.run_id:
        raise PreparationError('run_identity_changed')
    if text(fields, 'workflow_version') not in ('editorial-v2', 'editorial-simple-v1'):
        raise PreparationError('workflow_version_unknown')
    if any((run.directory / name).exists() for name in ('research.attempt', 'selection.attempt', 'writing.attempt')):
        raise PreparationError('workflow_version_changed')
    write_immutable(run.directory / 'v2-input.sha256', sha256(source.encode()).hexdigest().encode())
    cutoff = datetime_value(fields, 'cutoff')
    if not cutoff <= run.clock():
        raise PreparationError('selection_clock_invalid')
    context = '\nCutoff: ' + cutoff.isoformat() + '\nSignals: ' + text(fields, 'signals') + '\nHistory: ' + text(fields, 'history')
    budget = EditBudget()
    rejected: set[str] = set()
    pool: DiscoveryPool | None = None
    for attempt in range(3):
        if budget.turns >= 4:
            raise PreparationError('editorial_budget_exhausted')
        directory = safe_output_root(run.directory, f'candidate-{attempt + 1:02}')
        directory.mkdir(exist_ok=True)
        write_immutable(directory / 'input.json', source.encode())
        if (run.directory / 'signals.rss').is_file():
            write_immutable(directory / 'signals.rss', (run.directory / 'signals.rss').read_bytes())
        store = StageStore(directory, provider)
        selection = select_sources(store, SelectionContext(context, frozenset(rejected), pool), run.clock)
        if selection is None:
            discovery_directory = pool.store.directory if pool is not None else directory
            context += '\nPrior unsuitable leads; choose a different evidence-supported issue:\n' + (discovery_directory / 'discovery.json').read_text()
            pool = None
            continue
        if selection.candidate.candidate_id in rejected:
            context += '\nRepeated rejected candidate is ineligible; choose a different issue.'
            continue
        writing = store.run(StageRequest('writing', prompts.BOUNDARY + '\n' + v2_prompts.WRITING
            + '\nComposition time: ' + selection.selected_at.isoformat()
            + '\nEvidence:\n' + encode_json(selection.candidate.evidence) + '\nCategories: ' + repr(CATEGORIES)
            + '\nHome topics: ' + repr(TOPICS), directory, source_urls=selection.candidate.urls))
        discovery_store = selection.pool.store if selection.pool is not None else store
        sessions = frozenset(store.receipt(stage).session_id for stage in ('decision', 'writing'))
        sessions |= {discovery_store.receipt('discovery').session_id}
        if text(fields, 'workflow_version') == 'editorial-v2':
            sessions |= {store.receipt('opportunity').session_id}
        if (directory / 'decision-repair/decision.receipt.json').is_file():
            sessions |= {StageStore(directory / 'decision-repair', provider).receipt('decision').session_id}
        outcome = edit_package(EditorialWork(run, directory, selection, writing, text(fields, 'history'), sessions, budget,
            text(fields, 'media_mode') == 'interactive' if fields.value.get('media_mode') is not None else False), provider)
        if outcome.package is not None:
            return outcome.package
        budget = outcome.budget
        rejected.add(selection.candidate.candidate_id)
        pool = selection.pool
        if pool is not None and not any(item.candidate_id not in rejected
                for item in discover((pool.store.directory / 'discovery.json').read_text(), run.clock())):
            pool = None
        context += '\nEditor rejected this topic; choose another:\n' + encode_json(selection.candidate.evidence)
    raise PreparationError('editorial_candidates_exhausted')
