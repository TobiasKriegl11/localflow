"""User vocabulary: names and terms whisper should get right (hotwords).

Plain text file in the config dir, one term per line, editable via the tray.
Reloaded automatically when the file changes — no restart needed.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

from localflow.config import config_dir

log = logging.getLogger(__name__)

_TEMPLATE = """\
# LocalFlow Wörterbuch / vocabulary
# Ein Name oder Begriff pro Zeile — z. B. Namen von Familie, Firma, Projekten.
# One name or term per line. Lines starting with # are ignored.
"""

_cache: tuple[float, str] | None = None


def vocab_path() -> Path:
    return config_dir() / "vocabulary.txt"


def ensure_file() -> None:
    p = vocab_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_TEMPLATE, encoding="utf-8")


def hotwords() -> str | None:
    """Space-joined vocabulary for whisper, cached by file mtime."""
    global _cache
    p = vocab_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    if _cache is None or _cache[0] != mtime:
        terms = [line.strip() for line in p.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        _cache = (mtime, " ".join(terms))
        log.info("Vocabulary loaded: %d terms", len(terms))
    return _cache[1] or None


def open_in_editor() -> None:
    ensure_file()
    if sys.platform == "win32":
        os.startfile(vocab_path())  # default text editor
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-t", str(vocab_path())])
    else:
        subprocess.Popen(["xdg-open", str(vocab_path())])
