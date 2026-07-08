"""Subtle audio feedback: rising blip on record start, falling blip on stop."""

import logging

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

_RATE = 44_100


def _blip(freq: float, seconds: float = 0.06, volume: float = 0.15) -> np.ndarray:
    t = np.linspace(0, seconds, int(_RATE * seconds), endpoint=False)
    tone = np.sin(2 * np.pi * freq * t)
    fade = np.minimum(1.0, np.minimum(t, seconds - t) / 0.012)  # click-free edges
    return (tone * fade * volume).astype(np.float32)


_START = np.concatenate([_blip(660), _blip(880)])
_STOP = np.concatenate([_blip(880), _blip(660)])


def _play(tone: np.ndarray) -> None:
    try:
        sd.play(tone, _RATE)  # non-blocking; replaces any previous blip
    except Exception:
        log.debug("Sound feedback unavailable", exc_info=True)


def play_start() -> None:
    _play(_START)


def play_stop() -> None:
    _play(_STOP)
