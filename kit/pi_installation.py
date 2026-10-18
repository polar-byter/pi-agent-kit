"""Install the Pi kit into a separate project without copying secrets or caches."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .task_control_state import plain_path
from .pi_configuration import PI_PACKAGE, PI_VERSION, locate_pi_command

MANIFEST = Path('.metrics/.pi-kit-installation.json')
IGNORE_LINES = ('.metrics/', '.pi/', '.tools/', '.env', '.env.*', '__pycache__/', '*.pyc')
ROOT_FILES = ('AGENTS.md', 'pi-kit.json', 'install.py', 'install.cmd', 'install.sh', 'start.cmd', 'start.sh',
              'README.md', 'README.en.md', 'SOURCE.md', 'LICENSE')
TREES = ('kit', 'docs', 'readme_gif', 'examples')
SKIP = {'.git', '.metrics', '__pycache__', '.venv', 'node_modules', '.aws', '.ssh', '.codex', '.agents', 'auth.json', 'credentials.json'}


class InstallError(ValueError):
    """An installation failure that leaves existing project files intact."""


def payload(source: Path) -> dict[str, bytes]:
    """Read an explicit distributable allowlist. Never copy journals or saved keys."""
    source = plain_path(Path(source).absolute())
    files = {}
    for name in ROOT_FILES:
        path = plain_path(source / name)
        if not path.is_file():
            raise InstallError('The kit download is incomplete. Extract the full ZIP archive first.')
        files[name] = path.read_bytes()
    agents = files['AGENTS.md'].decode('utf-8')
    start, end = agents.find('## Work plan (memory)'), agents.find('## Source snapshot boundaries')
    if 0 <= start < end:
        agents = agents[:start] + ('## Work plan (memory)\n'
            '- Keep the active work plan in `currentsteps.md` in this project root. Create it if missing.\n'
            '- Read it at session start and update it after major steps. This installed project uses a local plan.\n\n') + agents[end:]
        files['AGENTS.md'] = agents.encode('utf-8')
    for tree in TREES:
        folder = plain_path(source / tree)
        if not folder.is_dir():
            raise InstallError('The kit download is incomplete. Extract the full ZIP archive first.')
        for current, dirs, names in os.walk(folder, followlinks=False):
            for name in dirs + names:
                path = Path(current) / name
                if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                    raise InstallError('The kit contains a link. Use an extracted official kit archive.')
            dirs[:] = [name for name in dirs if name.lower() not in SKIP and not name.lower().startswith('.env')]
            for name in names:
                if name.lower() in SKIP or name.lower().startswith('.env') or name.endswith(('.pyc', '.pyo')):
                    continue
                path = Path(current) / name
                files[path.relative_to(source).as_posix()] = path.read_bytes()
    return files


def project_path(value: str, source: Path) -> Path:
    """Require a separate absolute project folder, without following links."""
    if not value.strip():
        raise InstallError('Choose a project folder first.')
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise InstallError('Enter a full folder path, for example D:\\Projects\\my-project.')
    try:
        path = plain_path(path.absolute())
    except (OSError, ValueError):
        raise InstallError('Choose a regular folder, not a symbolic link or junction.') from None
    source = Path(source).resolve()
    canonical_destination = path.resolve()
    if path == Path(path.anchor) or canonical_destination.is_relative_to(source) or source.is_relative_to(canonical_destination):
        raise InstallError('Choose a separate project folder outside the downloaded kit.')
    if path.exists() and not path.is_dir():
        raise InstallError('This path is a file. Choose a folder instead.')
    return path


def installed(project: Path) -> bool:
    """A previous installation can reopen settings; never silently upgrade it."""
    try:
        value = json.loads(plain_path(project / MANIFEST).read_text(encoding='utf-8'))
        return value.get('format') == 1 and all(plain_path(project / name).is_file()
            for name in ('AGENTS.md', 'pi-kit.json', 'kit/run_pi.py'))
    except (OSError, ValueError, AttributeError):
        return False


def install_project(source: Path, destination: str) -> dict:
    """Create missing folders and install without overwriting existing project data.

    Preflight all conflicts. Exclusive file creation prevents a race from replacing
    user files. On failure remove only this call's unchanged files and empty dirs.
    Existing model settings, project code, TASK.md and README.md remain untouched.
    """
    project = project_path(destination, source)
    if installed(project):
        return {'project': str(project), 'reused': True, 'files': 0}
    files = payload(source)
    for name in ('README.md', 'README.en.md', 'SOURCE.md', 'LICENSE'):
        if (project / name).is_file():
            files.pop(name, None)
    for name in ('kit', 'AGENTS.md', 'pi-kit.json', 'opencode.json', '.pi/kit-runtime.json', '.pi/kit-models.json'):
        if (project / name).exists():
            raise InstallError('This folder already has Pi configuration or a kit. Choose another folder; nothing was replaced.')
    for name in files:
        target = plain_path(project / name)
        if target.exists() or any(parent.exists() and not parent.is_dir() for parent in target.parents):
            raise InstallError('Some kit files already exist in this folder. Choose another folder; nothing was replaced.')
    created, directories = {}, []
    ignore = plain_path(project / '.gitignore')
    old_ignore = ignore.read_bytes() if ignore.exists() else None
    ignore_bytes = (old_ignore or b'') + b'\n# Pi Kit: local settings and task journals\n' + '\n'.join(IGNORE_LINES).encode() + b'\n'
    def mkdir(path):
        if path.is_dir():
            return
        mkdir(path.parent)
        path.mkdir()
        directories.append(path)
    def create(path, content):
        with path.open('xb') as stream:
            created[path] = b''
            try:
                stream.write(content)
                stream.flush()
            except OSError:
                try:
                    stream.close()
                except OSError:
                    pass
                created[path] = path.read_bytes()
                raise
            created[path] = content
    def replace_ignore(content):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=project, prefix='.kit-ignore-', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            if ignore.read_bytes() != (old_ignore if content == ignore_bytes else ignore_bytes):
                raise InstallError('The project changed during installation. Try again.')
            os.replace(temporary, ignore)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    try:
        mkdir(project)
        for name, content in files.items():
            path = project / name
            mkdir(path.parent)
            create(path, content)
        if old_ignore is None:
            create(ignore, ignore_bytes)
        else:
            if ignore.read_bytes() != old_ignore:
                raise InstallError('The project changed during installation. Try again.')
            replace_ignore(ignore_bytes)
        mkdir((project / MANIFEST).parent)
        metadata = {'format': 1, 'runtime': 'pi', 'installed_at': datetime.now(timezone.utc).isoformat(),
                    'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        content = json.dumps(metadata, ensure_ascii=True, indent=2).encode()
        create(project / MANIFEST, content)
        mkdir(project / '.pi')
        create(project / '.pi/installation.json', json.dumps({'format': 1, 'runtime_root': str(Path(source).resolve())}, indent=2).encode())
    except BaseException:
        if old_ignore is not None and ignore.is_file() and ignore.read_bytes() == ignore_bytes:
            replace_ignore(old_ignore)
        for path, content in reversed(list(created.items())):
            if path.is_file() and path.read_bytes() == content:
                path.unlink()
        for path in reversed(directories):
            try:
                path.rmdir()
            except OSError:
                pass
        raise
    return {'project': str(project), 'reused': False, 'files': len(files)}



def install_pi_runtime(root: Path) -> list[str]:
    """Install the exact Pi version locally, keeping npm downloads beside the project."""
    root = Path(root).resolve()
    try:
        return locate_pi_command(root)
    except ValueError:
        pass
    node = shutil.which('node')
    npm = shutil.which('npm')
    if not node or not npm:
        raise InstallError('Install Node.js 22.19.0 or newer, then run setup again. Pi is installed on the project disk.')
    version_result = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=10,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        node_version = tuple(int(part) for part in version_result.stdout.strip().lstrip('v').split('.')[:3])
    except ValueError:
        node_version = ()
    if version_result.returncode or node_version < (22, 19, 0):
        raise InstallError('Pi requires Node.js 22.19.0 or newer. Update Node.js and run setup again.')
    runtime = root / '.tools/pi'
    runtime.mkdir(parents=True, exist_ok=True)
    package = {'private': True, 'dependencies': {PI_PACKAGE: PI_VERSION}}
    (runtime / 'package.json').write_text(json.dumps(package, indent=2) + '\n', encoding='utf-8')
    environment = os.environ.copy()
    environment['npm_config_cache'] = str(root / '.tools/npm-cache')
    temporary_directory = root / '.tools/temporary'
    temporary_directory.mkdir(parents=True, exist_ok=True)
    environment.update(TEMP=str(temporary_directory), TMP=str(temporary_directory), TMPDIR=str(temporary_directory))
    # Invoke npm's JavaScript entry point directly so Windows does not need a shell.
    resolved_npm = Path(npm).resolve()
    npm_script = resolved_npm if resolved_npm.name == 'npm-cli.js' else resolved_npm.parent / 'node_modules/npm/bin/npm-cli.js'
    if not npm_script.is_file():
        raise InstallError('The Node.js installation does not include npm-cli.js. Repair Node.js and try again.')
    result = subprocess.run([node, str(npm_script), 'install', '--ignore-scripts', '--omit=dev', '--no-audit', '--no-fund'],
                            cwd=runtime, env=environment, capture_output=True, text=True,
                            timeout=600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise InstallError('Pi installation failed. Check the internet connection and free space on the project disk.')
    return locate_pi_command(root)
