"""Control a native Pi terminal without owning a second conversation process."""
from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from urllib.request import Request

from .pi_rpc import PiControlError, process_identity


class InteractiveProcessReference:
    """Keep the same process identity checks as the subprocess adapter."""

    def __init__(self, identifier, identity):
        self.pid = identifier
        self.identity = identity
        self.returncode = None

    def poll(self):
        if process_identity(self.pid) != self.identity:
            self.returncode = 1
        return self.returncode


class PiInteractiveProcess:
    """Use the native terminal's authenticated control endpoint for one session."""

    def __init__(self, session):
        endpoint = session['interactive']
        self.session_identifier = session['id']
        self.identity = session['process']['identity']
        self.process = InteractiveProcessReference(session['process']['pid'], self.identity)
        self.port = endpoint['port']
        self.token = endpoint['token']
        self.settled = threading.Event()
        self.settled.set()

    def request(self, operation, timeout=20, **fields):
        from ..dashboard.launcher import local_request
        if self.process.poll() is not None:
            raise PiControlError('The native Pi terminal has exited')
        request = Request('http://127.0.0.1:' + str(self.port) + '/call',
            json.dumps(dict(session=self.session_identifier, operation=operation, **fields)).encode('utf-8'),
            {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with local_request(request, timeout=timeout) as response:
                result = json.load(response)
            if not result.get('success'):
                raise PiControlError('Native Pi did not confirm operation: ' + operation)
            data = result.get('data')
            if operation == 'get_state':
                if data.get('settled'):
                    self.settled.set()
                else:
                    self.settled.clear()
            elif operation == 'prompt':
                self.settled.clear()
            return data
        except (OSError, ValueError, KeyError) as error:
            raise PiControlError('Native Pi control was not confirmed; inspect its terminal') from error

    def stop_run(self):
        self.request('clear_queue')
        self.request('abort')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = self.request('get_state')
            if (state.get('settled') and not state.get('isStreaming')
                    and not state.get('isCompacting') and not state.get('pendingMessageCount')):
                return
            time.sleep(.05)
        raise PiControlError('Native Pi has not confirmed interruption')

    def close(self):
        """A service restart stops work and leaves the user's terminal open."""
        if self.process.poll() is None:
            self.stop_run()

    def shutdown(self):
        """Only explicit session deletion closes the native terminal."""
        self.stop_run()
        self.request('shutdown')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return
            time.sleep(.05)
        raise PiControlError('Native Pi has not confirmed shutdown')
