"""Run genuine browser actions through the official Playwright CLI."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

from .browser_runtime import browser_channel, ensure_browser_command
from .execution_watch import claim_attempt_watcher
from .task_control_state import plain_path
from .task_metrics import TaskMetrics

ACTIONS = ('open', 'goto', 'click', 'fill', 'type', 'press', 'keydown', 'keyup',
           'snapshot', 'screenshot', 'resize', 'console', 'eval', 'close')


def run_browser_action(project, task, action, arguments=()):
    """Keep one task browser session, serialize actions, and preserve honest evidence."""
    root = Path(project).resolve()
    metrics = TaskMetrics(root)
    if action != 'close':
        metrics.read_events_if_work_allowed(task)
    else:
        metrics.read(task)
    if action not in ACTIONS or any(not isinstance(value, str) for value in arguments):
        raise ValueError('Unknown browser action or non-text argument.')
    if any(value.startswith(('-s=', '--session', '--filename', '--config', '--profile', '--persistent')) for value in arguments):
        raise ValueError('The kit owns the browser session, output paths and temporary profile.')
    if action in ('open', 'goto'):
        if not arguments:
            raise ValueError('Browser navigation needs the application URL.')
        url = urlsplit(arguments[0])
        if url.scheme not in ('http', 'https') or url.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('Use the local application HTTP URL for this review.')
    folder = plain_path(metrics.task_dir(task) / 'browser')
    folder.mkdir(exist_ok=True)
    with claim_attempt_watcher(folder / 'actions.lock') as acquired:
        if not acquired:
            raise ValueError('Another browser action is in progress; wait for its result.')
        command, environment = ensure_browser_command(root)
        session = 'kit-' + hashlib.sha256((str(root) + task).encode()).hexdigest()[:20]
        command += ['--json', '-s=' + session, action, *arguments]
        screenshot = None
        if action == 'open':
            command += ['--browser', browser_channel(), '--idle-timeout=300000']
        if action == 'screenshot':
            screenshot = folder / (uuid.uuid4().hex + '.png')
            command += ['--filename=' + str(screenshot)]
        started = time.time()
        result = subprocess.run(command, cwd=folder, env=environment, capture_output=True, text=True,
                                encoding='utf-8', timeout=90,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise ValueError('Browser CLI did not return JSON: ' + (result.stderr or result.stdout)[-1000:]) from None
        if result.returncode or output.get('isError'):
            raise ValueError('Browser action failed: ' + str(output.get('error') or result.stderr)[-1500:])
        history = plain_path(folder / 'actions.jsonl')
        event = dict(action=action, arguments=list(arguments), at=started)
        with history.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + '\n')
        response = dict(action=action, browser_result=output)
        snapshot = output.get('result', {}).get('snapshot') if isinstance(output.get('result'), dict) else output.get('snapshot')
        if isinstance(snapshot, dict) and isinstance(snapshot.get('file'), str):
            snapshot_path = plain_path(folder / snapshot['file'])
            if snapshot_path.is_relative_to(folder) and snapshot_path.is_file():
                response['snapshot_text'] = snapshot_path.read_text(encoding='utf-8')[:12000]
        if screenshot:
            if not screenshot.is_file() or not screenshot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Playwright did not write a valid screenshot.')
            actions = [json.loads(line) for line in history.read_text(encoding='utf-8').splitlines()]
            last_open = max((index for index, item in enumerate(actions) if item['action'] == 'open'), default=0)
            receipt = screenshot.with_suffix('.json')
            proof = dict(engine='playwright-cli', task=task, project=str(root),
                         screenshot=screenshot.relative_to(root).as_posix(),
                         sha256=hashlib.sha256(screenshot.read_bytes()).hexdigest(), actions=actions[last_open:], at=time.time())
            receipt.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
            response.update(screenshot=proof['screenshot'], browser_evidence=receipt.relative_to(root).as_posix())
        return response


def main(arguments=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--task', required=True)
    parser.add_argument('action', choices=ACTIONS)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    options = parser.parse_args(arguments)
    try:
        print(json.dumps(run_browser_action(options.root, options.task, options.action, options.arguments), ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('Browser review unavailable: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
