"""Validate screenshots and browser receipts belonging to one exact task."""
import hashlib
import json
from pathlib import Path

from .task_control_state import plain_path


def validate_browser_evidence(project, task, reference):
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError('A completed UX scenario needs browser_evidence from kit.browser_review screenshot.')
    root = Path(project).resolve()
    folder = plain_path(root / '.metrics' / task / 'browser')
    receipt = plain_path(root / reference)
    if not receipt.is_relative_to(folder) or receipt.suffix != '.json':
        raise ValueError('Browser evidence must belong to this task browser folder.')
    try:
        record = json.loads(receipt.read_text(encoding='utf-8'))
        screenshot = plain_path(root / record['screenshot'])
        if (record.get('task') != task or record.get('project') != str(root)
                or record.get('engine') != 'playwright-cli' or not screenshot.is_relative_to(folder)
                or not any(action.get('action') in ('open', 'goto') for action in record.get('actions', []))):
            raise ValueError('Browser receipt does not describe this task and a real navigation.')
        content = screenshot.read_bytes()
        if not content.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(content).hexdigest() != record.get('sha256'):
            raise ValueError('Browser screenshot is missing, changed or not a PNG.')
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError('Cannot verify browser evidence: ' + str(error)) from error
    return receipt.relative_to(root).as_posix()
