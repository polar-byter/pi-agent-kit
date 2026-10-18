"""Task-scoped operations; source code and protective loop guards are preserved."""
from pathlib import Path
import os
import shutil
import threading
import uuid

from .. import task_control_state as state
from ..task_metrics import TaskMetrics, is_halted, session_id, valid_number
from .session_control import ControlError, SessionControl
from ..runtime_selection import create_session_gateway, uses_pi_runtime

ACTIONS = {'pause': 'pausing', 'resume': 'resuming', 'cancel': 'cancelling', 'delete': 'deleting'}


class TaskControls:
    def __init__(self, root: Path, gateway=None):
        self.root = Path(root).resolve()
        self.gateway = gateway or create_session_gateway(self.root)
        self._lock = threading.Lock()
        self._workers = {}

    def view(self, task):
        with self._lock:
            value = state.read_state(self.root, task)
            if value.get('status') in state.TRANSITIONS and task not in self._workers:
                # Do not duplicate a possibly admitted resume prompt after a process crash.
                try:
                    with state.operation_lock(self.root, task):
                        value = state.write_state(self.root, task, **dict(
                            {key: item for key, item in value.items() if key not in ('task', 'updated_at')},
                            status='error', allow_execution=False,
                            error='Дашборд перезапущен во время операции. Проверьте сессию или повторите остановку.'))
                except ValueError:
                    pass  # A different live dashboard worker owns this operation.
            return value

    def context(self, task, action):
        metrics = TaskMetrics(self.root)
        if action == 'delete' and not metrics.task_dir(task).exists() and state.read_state(self.root, task).get('session_removed'):
            return [], None
        events = metrics.read(task)
        if events[0].get('server_mode') in ('standalone', 'unknown') and not uses_pi_runtime(self.root):
            raise ValueError('Для этой задачи не подтверждён общий сервер Desktop. Управление из дашборда недоступно')
        if (metrics.task_dir(task) / 'events.jsonl').resolve().parent != metrics.task_dir(task):
            raise ValueError('Journal must not be redirected')
        sid = events[0].get('session')
        if not sid:
            if action == 'delete' and any(e['kind'] == 'finish' for e in events):
                return events, None
            raise ValueError('У задачи нет ID сессии OpenCode; управление выполнением недоступно')
        session_id(sid)
        # Refuse *any* other journal bound to the same root: deleting the native
        # tree would otherwise destroy another task's history, even when finished.
        for folder in (self.root / '.metrics').iterdir():
            if not folder.is_dir() or folder.name.startswith('.') or folder.name == task:
                continue
            if (folder / 'events.jsonl').exists():
                other = metrics.read(folder.name)
                if other[0].get('session') == sid:
                    raise ValueError('Эта сессия связана с другой задачей; управление отклонено')
        if action in ('pause', 'resume') and any(e['kind'] == 'finish' for e in events):
            raise ValueError('Завершённую задачу нельзя приостановить или продолжить')
        if action == 'resume' and is_halted(events):
            raise ValueError('Сработал защитный лимит. Сначала требуется решение пользователя по этому лимиту')
        return events, sid

    def pause_for_limit(self, task, signal):
        """Pause once for a bound failure; ignore failures predating a resume."""
        events, sid = self.context(task, 'pause')
        current = self.view(task)
        allowed = {sid, *(e['session'] for e in events if e['kind'] == 'attempt_session')}
        if (not isinstance(signal, dict) or signal.get('session') not in allowed
                or not valid_number(signal.get('at')) or signal['at'] < events[0]['at']
                or not isinstance(signal.get('message'), str) or not signal['message'].startswith('msg_')
                or not isinstance(signal.get('model'), str) or len(signal['model']) > 250):
            raise ValueError('Invalid quota observation')
        if current.get('status') not in (None, 'running') or signal['at'] <= current.get('quota_after', current.get('updated_at', 0)):
            return current
        return self.request(task, 'pause', limit=signal)

    def request(self, task, action, *, limit=None):
        if action not in ACTIONS:
            raise ValueError('Неизвестное действие')
        # Recovery is performed before taking the worker mutex again.
        self.view(task)
        with self._lock:
            current = state.read_state(self.root, task)
            if limit is not None and (current.get('status') not in (None, 'running') or limit['at'] <= current.get('quota_after', current.get('updated_at', 0))):
                return current
            if task in self._workers:
                if current.get('action') == action:
                    return current
                raise ValueError('Дождитесь завершения текущего действия')
            if (action, current.get('status')) in {('pause', 'paused'), ('resume', 'running'),
                                                  ('cancel', 'cancelled'), ('delete', 'deleted')}:
                return current
            if current.get('status') == 'deleted':
                raise ValueError('Задача уже удалена')
            if action == 'resume' and current.get('status') != 'paused':
                raise ValueError('Продолжить можно только подтверждённо приостановленную задачу')
            if action == 'pause' and current.get('status') in ('cancelled', 'error'):
                raise ValueError('Повторите остановку; пауза доступна для выполняющейся задачи')
            _, sid = self.context(task, action)
            operation = uuid.uuid4().hex
            # Lock is acquired before persisting the transition, not inside the thread.
            lease = state.operation_lock(self.root, task)
            lease.__enter__()
            try:
                details = {}
                if current.get('settings_revision'):
                    details['settings_revision'] = current['settings_revision']
                if limit is not None:
                    details.update(reason='provider_limit', quota_message=limit['message'],
                                   quota_session=limit['session'], quota_model=limit['model'],
                                   warning='Provider quota or rate limit reached. Task paused; change models or wait before continuing.')
                value = state.write_state(self.root, task, status=ACTIONS[action], action=action,
                                          operation_id=operation, session=sid, **details,
                                          session_removed=current.get('session_removed', False), allow_execution=False)
                worker = threading.Thread(target=self._run, args=(task, action, value, lease), daemon=True)
                self._workers[task] = worker
                worker.start()
            except BaseException:
                self._workers.pop(task, None)
                lease.__exit__(None, None, None)
                raise
            return value

    def stopped_tree(self, sid, clear_queue):
        previous = None
        for _ in range(4):
            tree = self.gateway.tree(sid)
            # Stop the coordinator first so it cannot launch new children.
            for child in tree:
                self.gateway.interrupt(child)
            if clear_queue:
                for child in tree:
                    self.gateway.clear_inbox(child)
            after = self.gateway.tree(sid)
            active = self.gateway.active() & set(after)
            if not active and set(after) == set(tree) and previous == set(after):
                return after
            previous = set(after)
        raise ControlError('Не все связанные сессии подтвердили остановку; повторите действие')

    def delete_metrics(self, task):
        folder = TaskMetrics(self.root).task_dir(task)
        if not folder.exists():
            return
        state.plain_path(folder)
        # Inspect every descendant before recursive deletion; never traverse links.
        for directory, dirs, files in os.walk(folder, followlinks=False):
            for name in dirs + files:
                state.plain_path(Path(directory) / name)
        if (folder / '.lock').exists():
            raise ControlError('Журнал ещё используется процессом кита; повторите удаление после его остановки')
        shutil.rmtree(folder)

    def _run(self, task, action, value, lease):
        details = {key: item for key, item in value.items() if key not in ('task', 'updated_at', 'status')}
        if action == 'resume':
            details['quota_after'] = value['updated_at']
        resume_issued = False
        try:
            sid = value['session']
            if sid:
                self.gateway.capabilities()
            # Revalidate journal bindings immediately before the native mutation.
            self.context(task, action)
            if action == 'resume':
                self.gateway.tree(sid)
                if self.gateway.active() & set(self.gateway.tree(sid)):
                    raise ControlError('Сессия уже активна; продолжение не отправлено')
                if value.get('settings_revision'):
                    self.gateway.prepare_resume(sid, task)
                # Let the metrics CLI run as soon as the admitted prompt starts.
                state.write_state(self.root, task, **dict(details, status='resuming', allow_execution=True))
                resume_issued = True
                self.gateway.resume(sid, task, value['operation_id'])
                status, message = 'running', 'Продолжение передано основной модели; частичные изменения требуют проверки.'
            else:
                if sid and not value.get('session_removed'):
                    tree = self.stopped_tree(sid, clear_queue=action != 'pause' or value.get('reason') == 'provider_limit')
                    details['sessions'] = tree
                    if action == 'delete':
                        self.gateway.remove(sid)
                        if any(row['id'] == sid for row in self.gateway.sessions()):
                            raise ControlError('Удаление основной сессии не подтверждено')
                        details['session_removed'] = True
                        state.write_state(self.root, task, **dict(details, status='deleting'))
                if action == 'delete':
                    self.delete_metrics(task)
                status = {'pause': 'paused', 'cancel': 'cancelled', 'delete': 'deleted'}[action]
                message = {'pause': 'Основная модель и все связанные исполнители приостановлены.',
                           'cancel': 'Задача отменена. Связанные сессии остановлены, очередь очищена.',
                           'delete': 'Сессии и метрики задачи удалены. Файлы приложения сохранены.'}[action]
            if action == 'pause' and value.get('reason') == 'provider_limit':
                message = value['warning']
            state.write_state(self.root, task, **dict(details, status=status, message=message, allow_execution=False))
        except Exception as error:
            message = str(error) if isinstance(error, (ControlError, ValueError)) else 'Не удалось выполнить действие. Результат не подтверждён.'
            status = 'paused' if action == 'resume' and not resume_issued else 'error'
            state.write_state(self.root, task, **dict(details, status=status, allow_execution=False, error=message[:500]))
        finally:
            lease.__exit__(None, None, None)
            with self._lock:
                self._workers.pop(task, None)
