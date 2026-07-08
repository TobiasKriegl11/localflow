"""Microphone capture with pre-roll ring buffer, level metering and silence tracking.

The stream runs continuously so the ~500 ms of audio *before* the hotkey press
is kept — the first word is never clipped. 16 kHz mono float32 (Whisper format).
"""

import logging
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
CHANNELS = 1
BLOCK_SIZE = 512  # 32 ms per block
PRE_ROLL_SECONDS = 0.5

MIN_SILENCE_THRESHOLD = 0.006  # RMS floor below which we call it silence
MAX_SILENCE_THRESHOLD = 0.02   # cap: pre-roll may contain speech (back-to-back takes)
NOISE_FLOOR_FACTOR = 2.5       # speech must exceed noise floor by this much


class Recorder:
    """Always-on mic stream; `start()` snapshots the pre-roll and begins a take."""

    def __init__(self, pre_roll_seconds: float = PRE_ROLL_SECONDS) -> None:
        n_blocks = max(1, int(pre_roll_seconds * SAMPLE_RATE / BLOCK_SIZE))
        self._ring: deque[np.ndarray] = deque(maxlen=n_blocks)
        self._frames: list[np.ndarray] = []
        self._recording = False
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        # Level/silence state (written on the audio thread, read anywhere).
        self.level = 0.0            # RMS of the latest block
        self._threshold = MIN_SILENCE_THRESHOLD
        self._last_voice = 0.0      # monotonic time voice was last heard
        self._started_at = 0.0
        self.speech_seen = False

    @property
    def recording(self) -> bool:
        return self._recording

    def open(self) -> None:
        """Start the persistent mic stream (call once at app startup)."""
        if self._stream is not None:
            return

        def callback(indata, _frames, _time, _status) -> None:
            self._process_block(indata.copy())

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=callback,
        )
        self._stream.start()
        log.info("Mic stream open (%.0f ms pre-roll)",
                 self._ring.maxlen * BLOCK_SIZE / SAMPLE_RATE * 1000)

    def _process_block(self, block: np.ndarray) -> None:
        """Audio-thread work; separated from the callback so tests can feed blocks."""
        self.level = float(np.sqrt(np.mean(np.square(block))))
        with self._lock:
            self._ring.append(block)
            if self._recording:
                self._frames.append(block)
                if self.level > self._threshold:
                    self._last_voice = time.monotonic()
                    self.speech_seen = True

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def start(self) -> None:
        """Begin a take, seeded with the pre-roll buffer."""
        with self._lock:
            self._frames = list(self._ring)
            # Calibrate the silence threshold from the pre-roll noise floor.
            if self._frames:
                floors = [float(np.sqrt(np.mean(np.square(b)))) for b in self._frames]
                # 25th percentile + cap: robust when the pre-roll contains speech.
                noise_floor = float(np.percentile(floors, 25))
                self._threshold = min(
                    max(MIN_SILENCE_THRESHOLD, noise_floor * NOISE_FLOOR_FACTOR),
                    MAX_SILENCE_THRESHOLD)
            now = time.monotonic()
            self._started_at = now
            self._last_voice = now  # grace period; don't stop instantly
            self.speech_seen = False
            self._recording = True

    def silence_seconds(self) -> float:
        """Seconds since voice was last heard in the current take."""
        return time.monotonic() - self._last_voice

    def take_seconds(self) -> float:
        return time.monotonic() - self._started_at if self._recording else 0.0

    def stop(self) -> np.ndarray:
        """End the take and return mono float32 audio at 16 kHz."""
        with self._lock:
            self._recording = False
            if not self._frames:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._frames, axis=0)
            self._frames = []
        return audio.reshape(-1)
