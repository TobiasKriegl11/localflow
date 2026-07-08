"""faster-whisper transcription. CPU-first; English-only or multilingual models.

Auto-detect mode uses a sticky-language prior: whisper's per-take detection is
weak on short utterances, but users rarely switch languages mid-session. Recent
takes' detection probabilities accumulate into a prior that outweighs a shaky
detection while a clearly confident one can still switch languages.
"""

import logging
import os
import time
from collections import defaultdict, deque

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)

DEFAULT_MODEL = "base.en"

LANG_HISTORY = 8   # how many takes of language evidence to remember
HINT_WEIGHT = 1.5  # pseudo-evidence for the language remembered across restarts
TOP_PROBS = 5      # per-take: keep only the top detection candidates

DETECT_CONFIDENT = 0.75  # below this, detection is unreliable -> decode tie-break
SCORE_SECONDS = 5.0      # tie-break decodes only this much audio per candidate
STICKY_EDGE = 0.15       # log-prob head start for the session's usual language
TIEBREAK_BONUS = 0.5     # extra evidence weight for a tie-break winner


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
        self.last_language = "en"
        # Rolling language evidence, newest last: {lang: detection prob} per take.
        self._lang_evidence: deque[dict[str, float]] = deque(maxlen=LANG_HISTORY)
        if language_hint:
            self._lang_evidence.append({language_hint: HINT_WEIGHT})
        log.info("Model loaded in %.1fs", time.perf_counter() - t0)

    def _language_prior(self) -> dict[str, float]:
        prior: dict[str, float] = defaultdict(lambda: 1.0)
        for observation in self._lang_evidence:
            for lang, prob in observation.items():
                prior[lang] += prob
        return prior

    def _pick_language(self, all_probs: list[tuple[str, float]]) -> str:
        """Detection probabilities × accumulated prior; best posterior wins."""
        prior = self._language_prior()
        return max(all_probs, key=lambda lp: lp[1] * prior[lp[0]])[0]

    def dominant_language(self) -> str:
        """The language this session's evidence points to ('' if none yet)."""
        if not self._lang_evidence:
            return ""
        prior = self._language_prior()
        return max(prior, key=prior.get)  # type: ignore[arg-type]

    def _score_language(self, audio: np.ndarray, lang: str) -> float:
        """Mean decoder log-prob of a short slice under `lang` (higher = better)."""
        piece = audio[: int(SCORE_SECONDS * 16_000)]
        segments, _ = self.model.transcribe(piece, language=lang, beam_size=1,
                                            condition_on_previous_text=False)
        probs = [seg.avg_logprob for seg in segments]
        return sum(probs) / len(probs) if probs else float("-inf")

    def _resolve_language(self, audio: np.ndarray, info,
                          allowed: list[str] | None = None) -> str:
        """Pick the take's language from detection + sticky prior (+ tie-break)."""
        raw = sorted(info.all_language_probs, key=lambda lp: -lp[1])
        if allowed:
            filtered = [lp for lp in raw if lp[0] in allowed]
            if filtered:
                raw = filtered
        evidence = dict(raw[:TOP_PROBS])
        chosen = self._pick_language(raw)
        # Tie-break when detection is shaky — or when it picked a language
        # outside the allowed set (its confidence says nothing about ours).
        outside = bool(allowed) and info.language not in (allowed or [])
        if info.language_probability < DETECT_CONFIDENT or outside:
            # Whisper is guessing: decode the top candidates and let the
            # decoder's own log-probs decide. Wrong-language decodes score
            # clearly worse. The usual language gets a small head start.
            sticky = self.dominant_language()
            candidates = list(dict.fromkeys(
                [raw[0][0], raw[1][0] if len(raw) > 1 else raw[0][0], chosen]))
            scores = {c: self._score_language(audio, c)
                      + (STICKY_EDGE if c == sticky else 0.0)
                      for c in candidates}
            best = max(scores, key=scores.get)  # type: ignore[arg-type]
            if all(s == float("-inf") for s in scores.values()):
                best = chosen  # nothing decodable in the slice; keep the prior
            log.info("Language tie-break %s -> %s (detection %s %.2f)",
                     {c: round(s, 2) for c, s in scores.items()}, best,
                     info.language, info.language_probability)
            evidence[best] = evidence.get(best, 0.0) + TIEBREAK_BONUS
            chosen = best
        self._lang_evidence.append(evidence)
        return chosen

    def warm_up(self) -> None:
        """Run a dummy pass so the first real dictation isn't slow."""
        self.model.transcribe(np.zeros(16_000, dtype=np.float32), beam_size=1)
        log.info("Model warmed up")

    def transcribe(self, audio: np.ndarray, language: str = "auto",
                   hotwords: str | None = None,
                   allowed_languages: list[str] | None = None) -> str:
        """Transcribe 16 kHz mono float32 audio; detects language when 'auto'.

        `hotwords` biases recognition toward user vocabulary (names, jargon).
        `allowed_languages` restricts auto-detection to plausible candidates
        (stops short German clips being labeled Dutch/Afrikaans etc.).
        """
        if audio.size == 0:
            return ""
        if self.is_english_only:
            lang = "en"
        else:
            lang = None if language == "auto" else language
        t0 = time.perf_counter()
        kwargs = dict(
            beam_size=5,  # ~0.1s slower than greedy, clearly better on real mics
            condition_on_previous_text=False,
            hotwords=hotwords,
            vad_filter=True,  # Silero VAD: trim silence/non-speech
            vad_parameters={"min_silence_duration_ms": 300},
        )
        segments, info = self.model.transcribe(audio, language=lang, **kwargs)
        if lang is None and info.all_language_probs:
            # Sticky prior: segments are decoded lazily, so overriding the
            # detected language only costs a second pass when it disagrees.
            chosen = self._resolve_language(audio, info, allowed_languages)
            if chosen != info.language:
                log.info("Language prior overrides detection %s (%.2f) -> %s",
                         info.language, info.language_probability, chosen)
                segments, info = self.model.transcribe(audio, language=chosen,
                                                       **kwargs)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        self.last_language = info.language or "en"
        log.info("Transcribed %.1fs audio in %.2fs [%s]: %r",
                 audio.size / 16_000, time.perf_counter() - t0,
                 self.last_language, text)
        return text
