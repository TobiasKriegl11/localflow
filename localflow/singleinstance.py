"""Single-instance guard: extra launches exit instead of stacking recorders."""

import logging
import sys

log = logging.getLogger(__name__)

_handle = None  # keep a reference for the process lifetime


def acquire() -> bool:
    """Return True if this is the only instance; False if one already runs."""
    global _handle
    if sys.platform == "win32":
        import ctypes

        ERROR_ALREADY_EXISTS = 183
        _handle = ctypes.windll.kernel32.CreateMutexW(None, False,
                                                      "Global\\LocalFlowSingleton")
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return False
        return True

    # macOS/Linux: advisory lock on a file in the config dir.
    import fcntl

    from localflow.config import config_dir

    path = config_dir() / "instance.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    _handle = open(path, "w")
    try:
        fcntl.flock(_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False
