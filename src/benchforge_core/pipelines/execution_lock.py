"""One process owns a pipeline run while it advances its persisted state."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path


class RunBusyError(RuntimeError):
    """The same run is already being advanced by another caller."""


def _acquire(stream):
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(stream):
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive_run(directory):
    """Reject competing execution; OS locks release after a process exits.

    Keep the marker after release so callers cannot lock different inodes for
    the same run. This covers a shared local filesystem; multi-host execution
    needs the scheduler's database lease protocol.
    """
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ".execution.lock"
    with marker.open("a+b", buffering=0) as stream:
        if marker.stat().st_size == 0:
            stream.write(b"\0")
        try:
            _acquire(stream)
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            raise RunBusyError(
                f"Pipeline run is already executing: {root}. "
                "Read its status or resume after the current executor exits."
            ) from None
        try:
            yield
        finally:
            _release(stream)
