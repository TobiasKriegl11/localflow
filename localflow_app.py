"""PyInstaller entry point: windowed app, file logging (no console)."""

import logging
import logging.handlers
import os
import sys

from localflow.config import config_dir

# No console in the windowed build: huggingface_hub's tqdm progress bars
# crash on sys.stderr=None. We render our own progress window instead.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


def main() -> None:
    log_dir = config_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(log_dir / "localflow.log",
                                             maxBytes=1_000_000, backupCount=2,
                                             encoding="utf-8"),
    ]
    if sys.stderr is not None:  # console present (dev run)
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from localflow.singleinstance import acquire
    if not acquire():
        logging.getLogger(__name__).warning(
            "LocalFlow is already running; exiting this instance.")
        return

    # Slim install: fetch the models on first launch, before loading anything.
    from localflow.download import ensure_models
    from localflow.paths import models_dir
    if not ensure_models(models_dir()):
        _fatal("Die Sprachmodelle konnten nicht geladen werden.\n"
               "Bitte Internetverbindung prüfen und LocalFlow neu starten.\n\n"
               "Could not download the speech models. Please check your "
               "internet connection and start LocalFlow again.")
        return

    from localflow.app import LocalFlowApp
    LocalFlowApp().run()


def _fatal(message: str) -> None:
    logging.getLogger(__name__).error(message)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("LocalFlow", message)
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    main()
