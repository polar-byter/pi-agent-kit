"""
Its contents are used to detect unexpected changes in source files, done by delegated executors,
and to provide snapshots for executor edits, including new and Git-ignored source files.
It is a black box to the executor, which is not trusted to modify source files correctly.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# Generated directories only. Source code must not be placed in these directories:
# they are excluded from the snapshot, so edits inside them are never detected.
# It is a way to exclude files that are not source files, and to avoid false positives in the snapshot.
GENERATED = {'.git', '.metrics', '.tools', '.pi', '__pycache__', '.venv', 'node_modules', 'target', 'build', 'dist', 'bin', 'obj'}


def normalize_delegated_path(root: Path, name: str) -> str:
    """
    Checks the file, the executor is allowed to edit, returns its normalized path.
    The returned path - similar to the form as the take_project_snapshot() keys:

    project-relative with "/" separators, so compare_project_snapshots() can match it.

    The file must already exist:
    because the Master Chief already created the skeleton before delegation.
    Raises ValueError with the exact reason when the path is rejected.
    """
    path = Path(name)

    # First check the text of the path, without touching the disk.
    if not path.parts:
        raise ValueError(f'Delegated file path is empty: {name!r}')
    if path.anchor:
        # anchor is the root part ("C:\\" or "/"); a relative path has none.
        raise ValueError(f'Delegated file must be project-relative, not absolute: {name}')
    if '..' in path.parts:
        raise ValueError(f'Delegated file must not leave the project with "..": {name}')
    if any(part in GENERATED for part in path.parts):
        # Generated directories are excluded from the snapshot, so edits there would go unnoticed.
        raise ValueError(f'Delegated file must not be in a generated directory: {name}')

    # Then check the real file on disk.
    absolute_path = root / path
    real_path = absolute_path.resolve()  # resolve() follows symlinks and junctions
    if not real_path.is_relative_to(root):
        raise ValueError(f'Delegated file resolves outside the project: {name}')
    if real_path != absolute_path.absolute():
        # absolute() keeps links as written; a difference means a link on the way.
        raise ValueError(f'Delegated file must not be a symlink or junction: {name}')
    if not absolute_path.is_file():
        raise ValueError(f'Delegated file must exist and be a regular file: {name}')

    return path.as_posix()


def take_project_snapshot(root: Path) -> dict[str, str]:
    """
    Hash files outside excluded directories, regardless of Git ignore rules.
    Why SHA-256: a short fixed-size fingerprint per file is enough for comparison,
    so no file copies are stored, and two different contents practically never get the same hash.
    Returns {project-relative POSIX path: SHA-256 hex digest}.
    These hashes allow later comparison; they do not prevent or restore edits.
    """
    files_of_the_snapshot = {}
    #followlinks=False: do not follow symlinks, to avoid infinite loops and to avoid including files outside the project.
    for current, dirs, names in os.walk(root, followlinks=False):
        # [:] we modify existing dirs not create a new list,
        # so that os.walk() does not recurse into excluded directories.
        # ;walk uses the original dirs list to recurse, so we need to modify it in place.
        dirs[:] = sorted(d for d in dirs if d not in GENERATED)
        for name in dirs + names:
            path = Path(current) / name
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                raise ValueError(f'Snapshot cannot follow a symlink or junction: {path}')
        for name in sorted(names):
            path = Path(current) / name
            # why relative path: the "before" snapshot we made in one folder,
            # but the "after" snapshot may be made in isolated environments,
            # in a copy of the project  - it is the .metrics/<ID>/workspaces.
            # so we need to use relative paths to compare the two snapshots, and not absolute paths that may differ.
            files_of_the_snapshot[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files_of_the_snapshot


def compare_project_snapshots(before: dict[str, str], after: dict[str, str], allowed: list[str]) -> dict:
    """
    Compare two project snapshots and return {"changed": [...], "unexpected": [...]}.
    The "before" snapshot is usually the one taken before the delegated executor ran,
    the "after" snapshot is the one taken after it. With allowed=[] the function only
    answers whether anything changed at all (task_metrics.py uses it this way after tests).
    The "allowed" list is the list of files that are allowed to be changed by the delegated executor.
    The "changed" list is the list of files that have changed between the two snapshots.
    The "unexpected" list is the list of files that have changed but are not in the "allowed" list.
    """
    changed = sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))
    return dict(changed=changed, unexpected=[p for p in changed if p not in allowed])


def review_checks(checks_file: Path) -> list[dict]:
    """Require explicit requirement/code/test evidence; correctness remains reviewer judgement.
    checks_file is .metrics/<ID>/<work_item>-checks.json: the Master Chief writes it during
    the review and passes it as `task_metrics.py review --result accepted --checks <file>`.
    This function checks only the form of every entry; task_metrics.py then checks that
    the entries cover every recorded requirement exactly once.
    """
    # utf-8-sig also accepts a BOM: PowerShell writes UTF-8 files with one by default.
    checks = json.loads(checks_file.read_text(encoding='utf-8-sig'))
    if not isinstance(checks, list) or not checks:
        raise ValueError('Review checks must be a non-empty JSON list')
    for item in checks:
        if (not isinstance(item, dict) or item.get('verified') is not True or
                any(not isinstance(item.get(k), str) or not item[k].strip()
                    for k in ('requirement', 'code', 'test'))):
            raise ValueError('Each check needs requirement, code, test and verified=true')
    return checks


def read_requirements(requirements_file: Path) -> list[str]:
    """Read and validate unique, non-blank requirements; delegate saves them.
    The file is plain JSON (.metrics/<ID>/<work_item>-requirements.json), no comments allowed.
    The main idea is to have a single source of truth for requirements, recorded before
    the executor starts: the executor gets them in its task, and the reviewer must
    prove every one of them in the checks file before the work can be accepted.
    Requirements must be unique, because the review compares them as a set.
    """
    requirements = json.loads(requirements_file.read_text(encoding='utf-8-sig'))  # BOM-tolerant, see review_checks

    if not isinstance(requirements, list):
        raise ValueError(f'Requirements must be a JSON list: {requirements_file}')
    if not requirements:
        # An empty list would let any work be accepted without evidence.
        raise ValueError(f'Requirements list is empty: {requirements_file}')
    for requirement in requirements:
        if not isinstance(requirement, str) or not requirement.strip():
            raise ValueError(f'Each requirement must be a non-blank string, got {requirement!r}: {requirements_file}')
    # set() drops repeats, so a shorter set means the list has duplicates.
    if len(set(requirements)) != len(requirements):
        raise ValueError(f'Requirements must be unique: {requirements_file}')

    return requirements
