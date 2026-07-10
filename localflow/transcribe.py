"""faster-whisper transcription. CPU-first; English-only or multilingual models.

Auto mode keeps ONE anchor: the language of the previous take. Whisper's own
language detection (restricted to the allowed set) drives each take, but the
session only leaves the anchor when detection picks a *different* language
*confidently* — an unsure or too-short detection sticks with the anchor. This
kills the mid-session flip-flop (a short "Ja." misheard as English no longer
derails a German session) while a real switch, which whisper detects with high
probability, still takes effect on the take it happens. Each take is decoded
exactly once, in the chosen language.
"""

import logging
import os
import threading
import time

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

DEFAULT_MODEL = "base.en"

# Leaving the anchor language requires whisper to detect the challenger with at
# least this RAW probability. Measured on de/en clips, correct detections land at
# 0.85-1.00 while the lone misdetection (a 1.2s "Ja." heard as English) sat at
# 0.61 — so a gate here rejects the flukes without blocking real switches.
# Deliberately the raw posterior, NOT renormalized over the allowed set:
# renormalizing that "Ja." (de 0.02 / en 0.61) would inflate it to 0.97 and let
# the fluke through. A corollary is that broadening `auto_languages` beyond two
# only makes switching *more* conservative (mass is split across more languages),
# which is the safe direction — retune this only if real switches feel sluggish.
SWITCH_DET_PROB = 0.70

_DECODE_OPTS = dict(
    beam_size=5,  # slightly slower than greedy, clearly better on real mics
    condition_on_previous_text=False,
    vad_filter=True,  # Silero VAD: trim silence/non-speech
    vad_parameters={"min_silence_duration_ms": 300},
)


def model_for_language(size: str, language: str) -> str:
    """Map a model size + language setting to the right whisper variant.

    English-only ('.en') models are more accurate for English; any other
    language (or auto-detect) needs the multilingual variant.
    """
    size = size.replace(".en", "")
    return f"{size}.en" if language == "en" else size


class Transcriber:
    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "cpu",
                 compute_type: str = "int8", language_hint: str = "") -> None:
        t0 = time.perf_counter()
        log.info("Loading whisper model %s (%s/%s)...", model_name, device, compute_type)
        from localflow.paths import bundled_whisper_dir
        bundled = bundled_whisper_dir(model_name)
        if bundled is not None:
            model_name = str(bundled)  # installer ships the model; no download
        threads = min(8, os.cpu_count() or 4)  # ~15% faster than the default 4
        try:
            # Offline-first: use the local cache without touching the network.
            self.model = WhisperModel(model_name, device=device, cpu_threads=threads,
                                      compute_type=compute_type, local_files_only=True)
        except Exception:
            log.info("Model not cached yet, downloading %s...", model_name)
            self.model = WhisperModel(model_name, device=device, cpu_threads=threads,
                                      compute_type=compute_type)
        self.is_english_only = model_name.endswith(".en")
        self.current_language = language_hint or ""  # auto-mode anchor
        self.last_language = language_hint or "en"
        self._take_lock = threading.Lock()  # takes never interleave on the model
        log.info("Model loaded in %.1fs", time.perf_counter() - t0)

    def warm_up(self) -> None:
        """Run a dummy pass so the first real dictation isn't slow."""
        self.model.transcribe(np.zeros(16_000, dtype=np.float32), beam_size=1)
        log.info("Model warmed up")

    # -- decoding -----------------------------------------------------------

    @staticmethod
    def _text(segs) -> str:
        """Join a decode's segments into one transcript string."""
        return " ".join(s.text.strip() for s in segs).strip()

    def _decode(self, audio: np.ndarray, lang: str, hotwords: str | None) -> str:
        segments, _ = self.model.transcribe(audio, language=lang,
                                            hotwords=hotwords, **_DECODE_OPTS)
        return self._text(list(segments))

    @staticmethod
    def _ranked_allowed(all_probs, allowed: list[str]):
        """Detection probs sorted desc, restricted to the allowed set if any.

        When detection returns nothing inside a non-empty allowed set, present
        the allowed languages themselves at zero confidence — so the caller
        picks an *allowed* language (unconfidently) instead of leaking a
        disallowed one that happened to top the raw detection.
        """
        ranked = sorted(all_probs, key=lambda lp: -lp[1])
        if allowed:
            within = [lp for lp in ranked if lp[0] in allowed]
            ranked = within or [(lang, 0.0) for lang in allowed]
        return ranked

    @staticmethod
    def _choose_language(det: str, p_det: float, anchor: str,
                         fallback: str) -> str:
        """Pick a take's language. Pure/deterministic so it can be unit-tested.

        Keep the anchor unless a *different* language is detected confidently.
        With no anchor, take a confident detection, else the stable fallback —
        so a single unsure short take never sets (or persists) the session
        language. `det`/`fallback` are assumed already inside the allowed set.
        """
        confident = p_det >= SWITCH_DET_PROB
        if anchor and (det == anchor or not confident):
            return anchor
        if confident:
            return det
        return fallback

    def _fallback_lang(self, det: str, allowed: list[str]) -> str:
        """A stable in-set language to hold when we have no confident signal."""
        last = self.last_language
        if last and (not allowed or last in allowed):
            return last
        if allowed:
            return allowed[0]
        return det

    # -- public API ----------------------------------------------------------

    def transcribe(self, audio: np.ndarray, language: str = "auto",
                   hotwords: str | None = None,
                   allowed_languages: list[str] | None = None) -> str:
        text, _ = self.transcribe_take(audio, language, hotwords, allowed_languages)
        return text

    def transcribe_take(self, audio: np.ndarray, language: str = "auto",
                        hotwords: str | None = None,
                        allowed_languages: list[str] | None = None
                        ) -> tuple[str, str]:
        """Transcribe one take; returns (text, language actually used).

        `hotwords` biases recognition toward user vocabulary (names, jargon).
        `allowed_languages` restricts auto mode to plausible candidates.
        """
        if audio.size == 0:
            return "", self.last_language
        with self._take_lock:
            t0 = time.perf_counter()
            if self.is_english_only:
                lang = "en"
                text = self._decode(audio, lang, hotwords)
            elif language not in ("auto", "", None):
                lang = language
                text = self._decode(audio, lang, hotwords)
            else:
                text, lang = self._auto_take(audio, hotwords, allowed_languages)
            self.last_language = lang
            log.info("Transcribed %.1fs audio in %.2fs [%s]: %r",
                     audio.size / 16_000, time.perf_counter() - t0, lang, text)
            return text, lang

    def _auto_take(self, audio: np.ndarray, hotwords: str | None,
                   allowed) -> tuple[str, str]:
        if isinstance(allowed, str):  # tolerate a hand-edited YAML scalar
            allowed = allowed.replace(",", " ").split()
        allowed = list(allowed or [])

        # Detection pass. Decoding is lazy, so the segments cost nothing until
        # (and unless) we consume them for the chosen language below.
        segments, info = self.model.transcribe(audio, language=None,
                                               hotwords=hotwords, **_DECODE_OPTS)
        ranked = self._ranked_allowed(info.all_language_probs
                                      or [(info.language, 1.0)], allowed)
        det, p_det = ranked[0]  # top allowed language + its raw probability

        cur = self.current_language
        if cur and allowed and cur not in allowed:
            cur = ""  # settings were narrowed after the anchor was set

        fallback = self._fallback_lang(det, allowed)
        target = self._choose_language(det, p_det, cur, fallback)
        log.info("Language: det=%s p=%.2f anchor=%s -> %s",
                 det, p_det, cur or "-", target)

        # One decode, in the chosen language (reuse the detection pass if it fits).
        text = (self._text(list(segments)) if info.language == target
                else self._decode(audio, target, hotwords))

        if self.current_language and target != self.current_language:
            log.info("Language switch %s -> %s", self.current_language, target)
        self.current_language = target
        return text, target
