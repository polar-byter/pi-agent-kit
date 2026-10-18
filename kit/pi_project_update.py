"""Update only kit-owned files after checking the previous installation hashes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from .pi_installation import InstallError, MANIFEST, installed, payload, project_path
from .task_control_state import plain_path


def stop_project_services_for_update(project):
    """Require stopped work before changing the code used by the local services."""
    from .runtimes.pi_gateway import PiSessionControl
    from .runtimes.pi_rpc import process_identity
    from .dashboard.launcher import stop_dashboard
    registry = project / '.pi/kit-service/registry.json'
    if registry.is_file():
        for session in json.loads(registry.read_text(encoding='utf-8'))['sessions'].values():
            reference = session.get('process', {})
            if session.get('interactive') and reference and process_identity(reference['pid']) == reference['identity']:
                raise InstallError('Close the project Pi terminal with /quit before updating the kit.')
    if (project / '.pi/kit-service/connection.json').exists():
        gateway = PiSessionControl(project)
        if gateway.active():
            raise InstallError('Pause every task in the project before updating the kit.')
        gateway.shutdown_service()
    stop_dashboard(project)


def update_project(source, destination):
    """Refuse edited kit files before replacing anything; preserve application data."""
    source = Path(source).resolve()
    project = project_path(destination, source)
    if not installed(project):
        raise InstallError('This folder does not contain a Pi Kit installation.')
    manifest_path = plain_path(project / MANIFEST)
    previous = json.loads(manifest_path.read_text(encoding='utf-8'))
    owned = previous['files']
    desired = payload(source)
    for name in ('README.md', 'README.en.md', 'SOURCE.md', 'LICENSE'):
        if name not in owned and (project / name).exists():
            desired.pop(name, None)
    replacements = []
    updated_hashes = dict(owned)
    for name, content in desired.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise InstallError('Invalid kit file path.')
        target = plain_path(project / relative)
        if not target.is_relative_to(project):
            raise InstallError('A kit file escaped the project folder.')
        before = target.read_bytes() if target.is_file() else None
        if target.exists() and before is None:
            raise InstallError('A directory conflicts with a kit file: ' + name)
        if before is not None and before != content:
            if hashlib.sha256(before).hexdigest() != owned.get(name):
                raise InstallError('The kit file was edited; preserve or reconcile it before updating: ' + name)
        updated_hashes[name] = hashlib.sha256(content).hexdigest()
        if before != content:
            replacements.append((target, before, content))
    metadata = dict(previous, files=updated_hashes, updated_at=datetime.now(timezone.utc).isoformat())
    installation = plain_path(project / '.pi/installation.json')
    saved_installation = installation.read_bytes()
    new_installation = dict(json.loads(saved_installation), runtime_root=str(source))
    replacements += [(installation, saved_installation, json.dumps(new_installation, indent=2).encode()),
                     (manifest_path, manifest_path.read_bytes(), json.dumps(metadata, indent=2).encode())]
    stop_project_services_for_update(project)
    applied = []
    created_directories = []

    def ensure_directory(directory):
        if directory.exists():
            return
        ensure_directory(directory.parent)
        directory.mkdir()
        created_directories.append(directory)

    def replace_bytes(target, content):
        temporary = target.with_name('.kit-update-' + uuid.uuid4().hex)
        try:
            temporary.write_bytes(content)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    try:
        for target, before, content in replacements:
            plain_path(target)
            if (target.read_bytes() if target.is_file() else None) != before:
                raise InstallError('The project changed while updating: ' + str(target.relative_to(project)))
            ensure_directory(target.parent)
            replace_bytes(target, content)
            applied.append((target, before, content))
    except Exception:
        for target, before, content in reversed(applied):
            if target.is_file() and target.read_bytes() == content:
                if before is None:
                    target.unlink()
                else:
                    replace_bytes(target, before)
        for directory in reversed(created_directories):
            directory.rmdir()
        raise
    return dict(project=str(project), updated_files=len(applied) - 2)


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update', required=True, help='Existing project folder to update.')
    options = parser.parse_args(arguments)
    try:
        result = update_project(Path(__file__).resolve().parents[1], options.update)
        print('Pi Kit updated: ' + result['project'])
        print('Open start.cmd in that project to use the native Pi interface.')
        return 0
    except (OSError, ValueError) as error:
        print(str(error))
        return 1
