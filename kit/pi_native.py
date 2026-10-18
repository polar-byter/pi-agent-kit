"""Open the official Pi terminal UI with the project's selected Chief model."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

from .pi_configuration import locate_pi_command, pi_process_environment
from .runtimes.pi_broker import write_private_json
from .runtime_selection import create_session_gateway


def launch_native_pi(project_root, options):
    """Let Pi render its own editor, transcript and session commands in this terminal."""
    command = locate_pi_command(project_root)
    if len(command) != 2:
        raise ValueError('Native terminal integration requires the pinned local Pi package')
    package_root = Path(command[1]).parents[2]
    if not (package_root / 'dist/index.js').is_file():
        raise ValueError('The Pi SDK is missing. Reinstall the pinned project runtime.')
    gateway = create_session_gateway(project_root)
    gateway.call('service.health')
    transcript = None
    if options.session:
        from .run_pi import find_task_for_session
        task = find_task_for_session(project_root, options.session)
        if options.task and options.task != task:
            raise ValueError('--task does not match the selected session')
        transcript = gateway.call('session.releaseForInteractive', {'sessionID': options.session})['transcript']
    metadata = dict(root=str(project_root), packageRoot=str(package_root), session=options.session,
                    transcript=transcript, task=options.task, prompt=options.prompt,
                    noBrowser=options.no_browser)
    context_file = project_root / '.pi/kit-service/native-launch' / (uuid.uuid4().hex + '.json')
    write_private_json(context_file, metadata)
    try:
        return subprocess.call([command[0], str(project_root / 'kit/pi/native_chief.mjs'), str(context_file)],
                               cwd=project_root, env=pi_process_environment(project_root))
    finally:
        context_file.unlink(missing_ok=True)
