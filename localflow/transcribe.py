"""faster-whisper transcription. CPU-first; English-only or multilingual models.

Auto mode keeps ONE anchor: the language of the previous take. Each take is
decoded in the expected language; when whisper's detection disagrees with the
anchor — or is unsure between the allowed languages — the take is decoded in
both candidates and the challenger wins only if its full-take decode reads
clearly better. So a single bad detection can never flip the session, while a
genuine language switch takes effect on the very take it happens.
"""

import logging
import os
import threading
import time

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

DEFAULT_MODEL = "base.en"

RENORM_CONFIDENT = 0.80  # below this (among allowed langs) detection is "unsure"
SWITCH_MARGIN = 0.05     # challenger must beat the anchor's decode by this (log-prob)
NO_SPEECH_MAX = 0.6      # segments above this are ignored when scoring a decode

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

    # -- decoding & scoring -------------------------------------------------

    @staticmethod
    def _score(segs) -> tuple[str, float, int]:
        """(text, duration-weighted mean log-prob of voiced segments, words)."""
        text = " ".join(s.text.strip() for s in segs).strip()
        voiced = [s for s in segs if s.no_speech_prob < NO_SPEECH_MAX]
        if not voiced or not text:
            return text, float("-inf"), 0
        dur = sum(s.end - s.start for s in voiced)
        lp = sum(s.avg_logprob * (s.end - s.start) for s in voiced) / max(dur, 1e-6)
        return text, lp, len(text.split())

    def _decode(self, audio: np.ndarray, lang: str,
                hotwords: str | None) -> tuple[str, float, int]:
        segments, _ = self.model.transcribe(audio, language=lang,
                                            hotwords=hotwords, **_DECODE_OPTS)
        return self._score(list(segments))

    @staticmethod
    def _ranked_allowed(all_probs, allowed: list[str]):
        """Detection probs sorted desc, restricted to the allowed set if any."""
        ranked = sorted(all_probs, key=lambda lp: -lp[1])
        if allowed:
            within = [lp for lp in ranked if lp[0] in allowed]
            if within:
                ranked = within
        return ranked

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
                text, _, _ = self._decode(audio, lang, hotwords)
            elif language not in ("auto", "", None):
                lang = language
                text, _, _ = self._decode(audio, lang, hotwords)
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

        # Detection pass. Decoding is lazy, so unused segments cost nothing.
        segments, info = self.model.transcribe(audio, language=None,
                                               hotwords=hotwords, **_DECODE_OPTS)
        ranked = self._ranked_allowed(info.all_language_probs
                                      or [(info.language, 1.0)], allowed)
        det = ranked[0][0]
        confidence = (ranked[0][1] / (ranked[0][1] + ranked[1][1])
                      if len(ranked) > 1 else 1.0)

        cur = self.current_language
        if cur and allowed and cur not in allowed:
            cur = ""  # settings were narrowed after the anchor was set
        if not cur:
            cur = det

        targets = {cur, det}
        if confidence < RENORM_CONFIDENT and len(targets) == 1 and len(ranked) > 1:
            targets.add(ranked[1][0])  # unsure detection: verify vs the runner-up

        decodes: dict[str, tuple[str, float, int]] = {}
        if info.language in targets:
            decodes[info.language] = self._score(list(segments))
        for lang in targets - decodes.keys():
            decodes[lang] = self._decode(audio, lang, hotwords)

        winner = cur
        challenger = next((c for c in targets if c != cur), None)
        if challenger is not None:
            _, s_cur, n_cur = decodes[cur]
            _, s_ch, n_ch = decodes[challenger]
            # A much shorter decode is a hallucination tell, not real speech.
            suspect = n_ch * 2 < n_cur
            if s_ch > s_cur + SWITCH_MARGIN and not suspect:
                winner = challenger
            log.info("Language check %s %.2f vs %s %.2f (det %s p=%.2f) -> %s",
                     cur, s_cur, challenger, s_ch, det,
                     info.language_probability, winner)
        if self.current_language and winner != self.current_language:
            log.info("Language switch %s -> %s", self.current_language, winner)
        self.current_language = winner
        return decodes[winner][0], winner
