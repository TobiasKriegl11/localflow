"""Hardware detection → whisper model tier.

≤8 GB RAM: tiny/base · ≥15 GB: small.en · NVIDIA GPU present: try CUDA.
No third-party deps: ctypes on Windows, sysctl on macOS.
"""

import ctypes
import logging
import shutil
import subprocess
import sys

log = logging.getLogger(__name__)


def total_ram_gb() -> float:
    try:
        if sys.platform == "win32":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullTotalPhys / 1024**3
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) / 1024**3
    except Exception:
        log.exception("RAM detection failed")
    return 8.0  # conservative default


def has_nvidia_gpu() -> bool:
    return shutil.which("nvidia-smi") is not None


# Empirical (i5-1235U): small.en is ~3.5x slower than base.en. base.en must
# finish 5s of audio in <=0.4s for projected small.en time to stay ~1.3s.
FAST_CPU_BASE_SECONDS = 0.4


def benchmark_base_seconds(model) -> float:
    """Time an already-loaded base.en model on 5s of fixed synthetic audio."""
    import time

    import numpy as np

    rng = np.random.default_rng(42)
    audio = (rng.standard_normal(5 * 16_000) * 0.05).astype(np.float32)
    model.transcribe(audio[:16_000], beam_size=1)  # warm
    t0 = time.perf_counter()
    segments, _ = model.transcribe(audio, beam_size=1, language="en")
    list(segments)
    return time.perf_counter() - t0


def pick_tier() -> tuple[str, str]:
    """Return (initial_model, device). base.en first; upgrade decided by benchmark."""
    ram = total_ram_gb()
    device = "cuda" if has_nvidia_gpu() else "cpu"
    model = "tiny.en" if ram < 6 else "base.en"
    log.info("Auto-tier: %.1f GB RAM, gpu=%s -> start with %s on %s",
             ram, has_nvidia_gpu(), model, device)
    return model, device


def decide_upgrade(base_seconds: float, device: str) -> str | None:
    """After benchmarking base.en, return an upgrade model or None to stay."""
    if device == "cuda":
        return "small.en"  # GPU has headroom regardless
    if base_seconds <= FAST_CPU_BASE_SECONDS and total_ram_gb() >= 8:
        return "small.en"
    return None
