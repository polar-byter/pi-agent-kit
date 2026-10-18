"""Explicit model revisions for paused tasks; historical attempts stay immutable."""
from contextlib import contextmanager, ExitStack
import hashlib
import json
from pathlib import Path
import time
import uuid

from . import task_control_state as state
from .runtime_selection import load_project_model_choices, uses_pi_runtime


def prepared_configuration_path(project_root):
    """Select the prepared file whose contents a paused-task revision records."""
    relative_path = '.pi/kit-runtime.json' if uses_pi_runtime(project_root) else '.opencode/opencode.jsonc'
    return Path(project_root) / relative_path


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def revision(root, task, reference):
    from .task_metrics import TaskMetrics
    if not isinstance(reference, str) or len(reference) != 32 or any(c not in '0123456789abcdef' for c in reference):
        raise ValueError('Invalid model settings revision')
    path = state.plain_path(TaskMetrics(root).task_dir(task) / 'model-settings' / (reference + '.json'))
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('task') != task or value.get('revision') != reference or not isinstance(value.get('choices'), dict):
        raise ValueError('Model settings revision does not match this task')
    return value


def references(root, choices):
    if uses_pi_runtime(root):
        from .pi_configuration import resolve_role_model_references
        return resolve_role_model_references(root, choices)
    from .run_opencode import strip_jsonc
    config = json.loads(strip_jsonc((root / 'opencode.jsonc').read_text(encoding='utf-8-sig')))
    overlay = json.loads(strip_jsonc((root / '.opencode/opencode.jsonc').read_text(encoding='utf-8')))
    result = {}
    for field, agent in (('masterChief', 'build'), ('executors', 'executor'), ('bugFixer', 'bug-fixer')):
        if field == 'bugFixer' and not choices.get(field):
            continue
        value = overlay.get('agents', {}).get(agent, {}).get('model') or config.get('agents', {}).get(agent, {}).get('model') or config.get('model')
        if not isinstance(value, str) or '/' not in value:
            raise ValueError('A model reference is required for ' + field)
        result[field] = value
    return result


def verify_revision(root, task, reference):
    value = revision(root, task, reference)
    overlay = prepared_configuration_path(root).read_bytes()
    if (fingerprint(load_project_model_choices(root)) != value['choices_hash'] or
            hashlib.sha256(overlay).hexdigest() != value['overlay_hash']):
        raise ValueError('Model settings changed. Prepare the selected runtime again before continuing.')
    return value


@contextmanager
def preparation(root):
    """Lock all unfinished bound tasks, verify their pause, then record a revision."""
    from .task_metrics import TaskMetrics
    from .dashboard.controls import TaskControls
    root = Path(root).resolve()
    metrics = TaskMetrics(root)
    controls = TaskControls(root)
    tasks = []
    with ExitStack() as stack:
        for journal in sorted((root / '.metrics').glob('*/events.jsonl')):
            events = metrics.read(journal.parent.name)
            if not events[0].get('session') or any(e['kind'] == 'finish' for e in events):
                continue
            task = journal.parent.name
            current = state.read_state(root, task)
            if current.get('status') in ('cancelled', 'deleted'):
                continue
            if current.get('status') != 'paused':
                raise ValueError('Finish or cancel isolated work, or pause the task, before preparing new model settings; saving a draft is allowed')
            stack.enter_context(state.operation_lock(root, task))
            _, sid = controls.context(task, 'pause')
            tree = controls.gateway.tree(sid)
            if controls.gateway.active() & set(tree):
                raise ValueError('Linked sessions are still active. Pause the task again before changing models.')
            tasks.append((task, sid, current))
        expected_choices = fingerprint(load_project_model_choices(root))
        yield
        if not tasks:
            return
        choices = load_project_model_choices(root)
        if fingerprint(choices) != expected_choices:
            raise ValueError('Model settings changed. Prepare the selected runtime again before continuing.')
        selected = references(root, choices)
        controls.gateway.prepare_models(choices, selected)
        for task, sid, current in tasks:
            controls.gateway.switch_model(sid, selected['masterChief'])
            identifier = uuid.uuid4().hex
            value = dict(task=task, revision=identifier, prepared_at=time.time(), choices=choices,
                         choices_hash=fingerprint(choices), models=selected,
                         overlay_hash=hashlib.sha256(prepared_configuration_path(root).read_bytes()).hexdigest())
            folder = state.plain_path(metrics.task_dir(task) / 'model-settings')
            folder.mkdir(exist_ok=True)
            with (folder / (identifier + '.json')).open('x', encoding='utf-8') as handle:
                json.dump(value, handle, ensure_ascii=True, indent=2)
            details = {k:v for k,v in current.items() if k not in ('task', 'updated_at')}
            state.write_state(root, task, **dict(details, settings_revision=identifier,
                message='Models prepared for this paused task. Click Resume to continue the same session.'))
