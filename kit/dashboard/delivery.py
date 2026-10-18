"""Completion evidence and safe project-local launch-file discovery."""
from pathlib import Path
from urllib.parse import urlencode

from . import tracking
from ..task_metrics import valid_number
from ..runtime_selection import uses_pi_runtime

LAUNCH_FILES = ('run.ps1', 'start.ps1', 'run.sh', 'start.sh', 'run.cmd', 'start.cmd',
                'run.bat', 'start.bat', 'run.py', 'start.py')
LAUNCH_EXTENSIONS = {'.ps1', '.sh', '.cmd', '.bat', '.py', '.js', '.mjs'}


def launch_file(root: Path, task: str) -> Path | None:
    """Resolve an explicit per-task result file or a conventional root launcher.

    The result record may name only a relative existing script inside this project.
    Hidden files, directories, links and unsupported extensions are never exposed.
    An invalid explicit record fails closed, instead of silently choosing another file.
    """
    result = tracking.read_json(tracking.progress_folder(root, task) / 'result.json')
    if result is not None:
        if not isinstance(result, dict) or not isinstance(result.get('launcher'), str):
            raise ValueError('Result needs a project-relative launcher')
        names = [result['launcher']]
    else:
        names = LAUNCH_FILES
    pi_project = uses_pi_runtime(root)
    for name in names:
        try:
            target = tracking.project_file(root, name)
        except FileNotFoundError:
            continue
        relative_name = target.relative_to(root).as_posix().lower()
        if pi_project and relative_name in ('start.cmd', 'start.sh'):
            if result is not None:
                raise ValueError('The managed Pi console is not an application launcher')
            continue
        if target.suffix.lower() not in LAUNCH_EXTENSIONS or target.stat().st_size > tracking.MAX_DOCUMENT:
            raise ValueError('Launch file must be a script up to 1 MiB')
        return target
    return None


def completion(root: Path, task: str, events: list[dict]) -> dict:
    """Show completion only after finish; verification is a distinct journal fact."""
    finished = next((event for event in events if event['kind'] == 'finish'), None)
    if not finished:
        return {'finished': False}
    closed = {event.get('delegation_id') for event in events if event['kind'] == 'review'}
    pending = sum(event['kind'] == 'delegation' and event['event_id'] not in closed for event in events)
    full = [event for event in events if event['kind'] == 'test' and event.get('phase') != 'baseline' and event.get('scope', 'full') == 'full']
    last = full[-1] if full else None
    ended = finished.get('ended', finished['at'])
    if not valid_number(ended):
        ended = finished['at']
    data = {'finished': True, 'verified': bool(last and last['status'] == 'passed' and type(last.get('tests')) is int and last['tests'] > 0 and not pending),
            'ended_at': ended, 'duration_seconds': max(0, int(ended - events[0]['at'])),
            'project_path': str(root.resolve()), 'pending': pending,
            'full_tests': {key: last.get(key) for key in ('at', 'status', 'tests')} if last else None,
            'launcher': None, 'ux': None}
    ux = next((event for event in reversed(events) if event['kind'] == 'ux_review'), None)
    if ux and ux.get('outcome') in ('completed', 'skipped', 'not_applicable'):
        data['ux'] = {key: ux[key] for key in ('outcome', 'reason', 'scenarios', 'fixed') if key in ux}
    try:
        target = launch_file(root, task)
        if target:
            data['launcher'] = {'name': target.relative_to(root).as_posix(), 'path': str(target),
                                'url': '/launch-file?' + urlencode({'task': task})}
    except (OSError, ValueError):
        data['launcher_error'] = 'Файл запуска недоступен; папку проекта можно открыть отдельно'
    return data
