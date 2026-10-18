"""User-only POSIX key storage; no project files or shell profiles are changed."""
import json
import os
from pathlib import Path
import tempfile

from ..task_control_state import plain_path


def location():
    selected = os.environ.get('XDG_CONFIG_HOME')
    base = Path(selected) if selected else Path.home() / '.config'
    if not base.is_absolute():
        base = Path.home() / '.config'
    return plain_path(base / 'pi-agent-kit' / 'keys.json')


def private(path):
    if path.exists() and os.name == 'posix':
        metadata = path.stat()
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise PermissionError('OpenCode Kit key storage must be accessible only to its owner.')


def read():
    path = location()
    if not path.exists():
        return {}
    private(path.parent)
    private(path)
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ValueError('OpenCode Kit key storage is invalid.')
    return value


def save(name, value):
    path = location()
    data = read()
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    private(path.parent)
    data[name] = value
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode='w', encoding='utf-8') as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=True)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
