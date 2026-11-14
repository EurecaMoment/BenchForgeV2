"""Canonical control calls for an independently installed Isaac dispatcher.

Only context and finish run in the configured backend Python. Rendering,
uploads, leases and executor recovery stay in the existing dispatcher.
"""
import json
from pathlib import Path
import subprocess

OVERLAY_VERSION = 'owned-context-backend-ack-v1'


def default_adapter_path():
    directory = Path(__file__).resolve().parent
    bundled = directory / 'capture_finish.py'
    if bundled.is_file():
        return bundled
    return directory.parents[1] / 'processes/dispatcher_control.py'


class ControlAdapterError(RuntimeError):
    def __init__(self, operation, detail):
        self.operation = operation
        super().__init__('Native capture ' + operation + ' rejected: ' + detail)


class CanonicalControl:
    def __init__(self, *, service_config, backend_python, adapter_path=None, timeout_seconds=20, runner=None):
        self.service_config = str(Path(service_config).resolve())
        # The invoked path determines the virtual environment on POSIX.
        self.backend_python = str(Path(backend_python).absolute())
        self.adapter_path = str(Path(adapter_path or default_adapter_path()).resolve())
        self.timeout_seconds = timeout_seconds
        self.runner = runner or subprocess.run

    def __call__(self, route, arguments=None):
        operations = {'/worker/context': 'context', '/worker/finish': 'finish'}
        if route not in operations:
            raise ValueError('Canonical capture control does not support this route')
        operation = operations[route]
        # Do not reconstruct identity, claim a new token, or drop the receipt.
        # The canonical Store validates task/revision/token/transport_retry.
        payload = json.dumps(arguments or {}).encode('utf8')
        command = [self.backend_python, '-B', self.adapter_path, '--config', self.service_config,
                   '--operation', operation]
        try:
            result = self.runner(command, input=payload, capture_output=True, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as error:
            raise ControlAdapterError(operation, 'canonical backend exceeded ' + str(self.timeout_seconds) + ' seconds') from error
        except OSError as error:
            raise ControlAdapterError(operation, str(error)) from error
        if result.returncode:
            detail = result.stderr.decode('utf8', errors='replace').strip() or result.stdout.decode('utf8', errors='replace').strip()
            raise ControlAdapterError(operation, detail or 'backend exited ' + str(result.returncode))
        try:
            value = json.loads(result.stdout)
        except (ValueError, UnicodeDecodeError) as error:
            raise ControlAdapterError(operation, 'canonical backend returned an invalid acknowledgement') from error
        if not isinstance(value, dict):
            raise ControlAdapterError(operation, 'canonical backend acknowledgement is not an object')
        return value
