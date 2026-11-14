"""Terminate collector and artifact subprocesses."""
import os
import signal
import subprocess


def terminate_process_tree(process, *, grace_seconds=10):
    """Stop a subprocess and descendants created inside its owned scope."""
    if process.poll() is not None:
        return

    if os.name == 'nt':
        try:
            subprocess.run(
                ['taskkill', '/PID', str(process.pid), '/T'],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=grace_seconds,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=grace_seconds,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            process.kill()
            process.wait()
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.terminate()
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            process.kill()
        process.wait()
