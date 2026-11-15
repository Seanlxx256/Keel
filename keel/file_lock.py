"""Fail-fast same-host advisory lock; never unlink a live lock inode."""
from contextlib import contextmanager
import os
from pathlib import Path

from .governance import GovernanceUnavailable


@contextmanager
def exclusive_file(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    stream=path.open('a+b');locked=False
    try:
        if os.name=='nt':
            import msvcrt
            if os.fstat(stream.fileno()).st_size==0:stream.write(b'\0');stream.flush()
            stream.seek(0)
            try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as error:raise GovernanceUnavailable('Controller path lock is busy or unavailable') from error
        else:
            import fcntl
            try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as error:raise GovernanceUnavailable('Controller path lock is busy or unavailable') from error
        locked=True
        yield
    finally:
        try:
            if locked:
                if os.name=='nt':
                    import msvcrt
                    stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        finally:stream.close()
