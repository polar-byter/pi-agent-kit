"""Choose the execution gateway without changing the task's review rules.

The project file selects a runtime. Old projects without that file keep their
OpenCode gateway so their journals and tests remain readable.
"""
from __future__ import annotations

import json
from pathlib import Path


def uses_pi_runtime(project_root: Path) -> bool:
    """Read the project's explicit runtime selection and reject unknown values."""
    selection_path = Path(project_root) / 'pi-kit.json'
    if not selection_path.exists():
        return False
    selection = json.loads(selection_path.read_text(encoding='utf-8-sig'))
    if not isinstance(selection, dict) or selection.get('runtime') not in ('pi', 'opencode'):
        raise ValueError('The project must select the pi or opencode runtime.')
    return selection['runtime'] == 'pi'


def create_session_gateway(project_root: Path):
    """Return the selected gateway; importing this function starts no service."""
    if uses_pi_runtime(project_root):
        from .runtimes.pi_gateway import PiSessionControl
        return PiSessionControl(project_root)
    from .dashboard.session_control import SessionControl
    return SessionControl(project_root)


def load_project_model_choices(project_root: Path) -> dict:
    """Read choices through the selected runtime's configuration adapter."""
    if uses_pi_runtime(project_root):
        from .pi_configuration import load_choices
    else:
        from .run_opencode import load_choices
    return load_choices(project_root)
