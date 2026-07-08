"""First-run model downloader with a small progress window (slim installs).

Downloads whisper base/base.en and the cleanup GGUF into the app's models dir.
Shows a tkinter progress window; progress is tracked by polling directory size.
"""

import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

WHISPER_REPOS = {
    "faster-whisper-base.en": "Systran/faster-whisper-base.en",
    "faster-whisper-base": "Systran/faster-whisper-base",
}
GGUF_REPO = "bartowski/Llama-3.2-1B-Instruct-GGUF"
GGUF_FILE = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"

TOTAL_BYTES = 1_100_000_000  # ~two whisper models + 1B GGUF, for the progress bar


def missing_models(models_dir: Path) -> list[str]:
    missing = [name for name in WHISPER_REPOS
               if not (models_dir / name / "model.bin").exists()]
    if not (models_dir / GGUF_FILE).exists():
        missing.append(GGUF_FILE)
    return missing


def _dir_bytes(path: Path) -> int:
    try:
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except OSError:
        return 0


def _download_all(models_dir: Path, missing: list[str], errors: list) -> None:
    try:
        from huggingface_hub import hf_hub_download, snapshot_download

        for name, repo in WHISPER_REPOS.items():
            if name in missing:
                snapshot_download(repo_id=repo, local_dir=models_dir / name)
        if GGUF_FILE in missing:
            hf_hub_download(repo_id=GGUF_REPO, filename=GGUF_FILE,
                            local_dir=models_dir)
    except Exception as e:  # surfaced in the UI thread
        log.exception("Model download failed")
        errors.append(e)


def ensure_models(models_dir: Path) -> bool:
    """Download any missing models with a progress window. True when all present."""
    missing = missing_models(models_dir)
    if not missing:
        return True
    log.info("First run: downloading models %s", missing)
    models_dir.mkdir(parents=True, exist_ok=True)

    errors: list = []
    worker = threading.Thread(target=_download_all,
                              args=(models_dir, missing, errors), daemon=True)
    worker.start()

    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("LocalFlow")
        root.geometry("420x120")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        tk.Label(root, text="LocalFlow richtet sich ein — Sprachmodelle werden "
                            "geladen (~1 GB, einmalig)…", wraplength=390).pack(pady=(16, 8))
        bar = ttk.Progressbar(root, length=380, maximum=100)
        bar.pack()
        pct = tk.Label(root, text="0%")
        pct.pack(pady=(4, 0))

        start_bytes = _dir_bytes(models_dir)
        goal = max(TOTAL_BYTES - start_bytes, 1)

        def tick() -> None:
            if not worker.is_alive():
                root.destroy()
                return
            done = _dir_bytes(models_dir) - start_bytes
            p = min(99, int(done / goal * 100))
            bar["value"] = p
            pct.config(text=f"{p}%")
            root.after(500, tick)

        root.after(500, tick)
        root.mainloop()
    except Exception:
        log.exception("Progress window unavailable; downloading headless")

    worker.join()
    if errors or missing_models(models_dir):
        log.error("Models still missing after download attempt")
        return False
    log.info("All models downloaded")
    return True
