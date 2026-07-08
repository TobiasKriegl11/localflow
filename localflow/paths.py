"""Model path resolution for dev checkouts and frozen (PyInstaller) builds."""

import sys
from pathlib import Path


def models_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Installed layout: <install dir>/LocalFlow.exe + <install dir>/models/
        return Path(sys.executable).parent / "models"
    return Path(__file__).resolve().parent.parent / "models"


def bundled_whisper_dir(model_name: str) -> Path | None:
    """Bundled CTranslate2 model dir (e.g. models/faster-whisper-base.en), if present."""
    d = models_dir() / f"faster-whisper-{model_name}"
    return d if (d / "model.bin").exists() else None


def llm_gguf_path() -> Path:
    return models_dir() / "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
