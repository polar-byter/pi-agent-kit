"""Keep one process responsible for observing an isolated attempt."""
from contextlib import contextmanager
import errno
import os

from .task_control_state import plain_path


@contextmanager
def claim_attempt_watcher(path):
    """Release ownership on process exit, including a crash, without deleting the lock file."""
    path = plain_path(path)
    with path.open('a+b') as handle:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def launch_summary(task, attempt):
    """Return the identifiers and next commands without repeating frozen requirements."""
    identifier = attempt['event_id']
    return dict(kind='launched', task=task, attempt_id=identifier,
                worker_id=attempt['worker_id'], work_item=attempt['work_item'],
                workspace=attempt['workspace'], supervision='automatic',
                watch_command=f'kit\\python.cmd -m kit.execution_controller --task {task} watch --attempt {identifier}',
                inspect_command=f'kit\\python.cmd kit/task_metrics.py inspect --task {task} --work-item {attempt["work_item"]}')
