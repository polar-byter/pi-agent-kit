"""One owned Pi process with correlated JSONL commands and settled notifications."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid


class PiControlError(RuntimeError):
    """A control result that could not be safely confirmed."""


def process_identity(process_identifier):
    """Distinguish an owned process from a later process reusing its identifier."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME))
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, int(process_identifier))
        if not handle:
            return None
        try:
            created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                          ctypes.byref(kernel_time), ctypes.byref(user_time)):
                raise PiControlError('Cannot verify the previous Pi process')
            exit_code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                raise PiControlError('Cannot verify the previous Pi process')
            if exit_code.value != 259:
                return None
            return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        from pathlib import Path
        # The executable name can contain spaces, so split after its closing bracket.
        fields = Path(f'/proc/{int(process_identifier)}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except FileNotFoundError:
        return None
    except OSError as error:
        raise PiControlError('Cannot verify the previous Pi process') from error


def terminate_verified_process(process_identifier, expected_identity):
    if process_identity(process_identifier) != expected_identity:
        return
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x0001 | 0x1000, False, int(process_identifier))
        if not handle:
            raise PiControlError('Previous Pi process could not be stopped')
        try:
            if process_identity(process_identifier) != expected_identity:
                return
            if not kernel.TerminateProcess(handle, 1):
                raise PiControlError('Previous Pi process could not be stopped')
        finally:
            kernel.CloseHandle(handle)
    else:
        import signal
        os.kill(int(process_identifier), signal.SIGTERM)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process_identity(process_identifier) != expected_identity:
            return
        time.sleep(.05)
    raise PiControlError('Previous Pi process has not confirmed its exit')


class PiRpcProcess:
    def __init__(self, command, workspace, environment, on_event=None):
        self.pending = {}
        self.events = []
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.settled = threading.Event()
        self.settled.set()
        self.on_event = on_event
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        self.process = subprocess.Popen(command, cwd=workspace, env=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1, **options)
        self.identity = process_identity(self.process.pid)
        threading.Thread(target=self._read_messages, daemon=True).start()

    def _read_messages(self):
        try:
            for line in self.process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get('type') == 'response':
                    with self.lock:
                        waiter = self.pending.get(event.get('id'))
                    if waiter is not None:
                        waiter.put(event)
                    continue
                with self.lock:
                    self.events.append(event)
                    self.events = self.events[-200:]
                if event.get('type') == 'agent_start':
                    self.settled.clear()
                if event.get('type') == 'agent_settled':
                    self.settled.set()
                if self.on_event:
                    try:
                        self.on_event(event)
                    except Exception:
                        # Persistence failures must not kill the pipe reader or report false idle.
                        self.settled.clear()
        finally:
            with self.lock:
                for waiter in self.pending.values():
                    waiter.put(None)

    def request(self, operation, timeout=20, **fields):
        identifier = uuid.uuid4().hex
        waiter = queue.Queue()
        with self.lock:
            self.pending[identifier] = waiter
        try:
            with self.write_lock:
                if self.process.poll() is not None:
                    raise PiControlError('Pi process exited; operation was not confirmed')
                self.process.stdin.write(json.dumps(dict(id=identifier, type=operation, **fields)) + '\n')
                self.process.stdin.flush()
            try:
                response = waiter.get(timeout=timeout)
            except queue.Empty as error:
                raise PiControlError('Pi did not confirm the operation in time') from error
            if not response or response.get('success') is not True:
                # Pi may include provider credentials in its error text.
                raise PiControlError('Pi did not confirm operation: ' + operation)
            return response.get('data')
        except (OSError, ValueError) as error:
            raise PiControlError('Pi communication was interrupted') from error
        finally:
            with self.lock:
                self.pending.pop(identifier, None)

    def stop_run(self):
        self.request('clear_queue')
        state = self.request('get_state')
        was_running = state.get('isStreaming') or state.get('isCompacting') or not self.settled.is_set()
        self.request('abort')
        self.request('clear_queue')
        if was_running and not self.settled.wait(15):
            raise PiControlError('Pi has not emitted agent_settled after interruption')
        state = self.request('get_state')
        if state.get('isStreaming') or state.get('isCompacting') or state.get('pendingMessageCount'):
            raise PiControlError('Pi is still active after interruption')

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()
