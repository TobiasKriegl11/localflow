"""Embedded LLM transcript cleanup via llama-cpp-python.

Runs Llama-3.2-1B-Instruct (Q4 GGUF) fully in-process. Every call has a hard
timeout; on timeout/error the raw Whisper text is returned so the app never hangs.
"""

import logging
import queue
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

from localflow.paths import llm_gguf_path

DEFAULT_MODEL_PATH = llm_gguf_path()
DEFAULT_TIMEOUT = 3.0

SYSTEM_PROMPT = (
    "You are a transcription formatter. Fix punctuation and capitalization, "
    "remove filler words, do NOT add, remove, or change meaning. "
    "Always answer in the same language as the input — never translate. "
    "Output only the corrected text — no preamble, no quotes, no explanation."
)

# Few-shot examples keep the 1B model terse and stop it dropping words.
# Languages without examples skip LLM cleanup (raw text) — safer than risking
# the model translating or mangling a language it handles poorly.
FEW_SHOT = {
    "en": [
        {"role": "user", "content": "um so i think we should uh move the meeting to friday"},
        {"role": "assistant", "content": "So I think we should move the meeting to Friday."},
        {"role": "user", "content": "hey did you get the uh the email i sent like yesterday"},
        {"role": "assistant", "content": "Hey, did you get the email I sent yesterday?"},
    ],
    "de": [
        {"role": "user", "content": "ähm also ich glaube wir sollten uns äh am dienstag treffen um den bericht zu besprechen"},
        {"role": "assistant", "content": "Also ich glaube, wir sollten uns am Dienstag treffen, um den Bericht zu besprechen."},
        {"role": "user", "content": "hast du äh die e-mail bekommen die ich dir gestern geschickt habe"},
        {"role": "assistant", "content": "Hast du die E-Mail bekommen, die ich dir gestern geschickt habe?"},
    ],
}

_FILLERS = {
    "en": {"um", "uh", "like", "so", "you", "know", "i", "mean", "a", "the"},
    "de": {"ähm", "äh", "halt", "also", "quasi", "sozusagen", "ja", "ne",
           "der", "die", "das", "ein", "eine", "und", "ich"},
}

_PREAMBLE_MARKERS = ("here is", "here's", "sure", "certainly", "corrected text",
                     "hier ist", "gerne", "korrigierte")

# Unambiguous verbal fillers, stripped deterministically (regex) before the LLM
# and on every fallback path. Per-language: German "um" means "in order to"!
_HARD_FILLERS = {
    "en": ("um", "uh", "uhm", "erm", "hmm"),
    "de": ("ähm", "äh", "mhm", "hmm"),
}


def strip_fillers(text: str, lang: str) -> str:
    """Remove unambiguous filler words; tidy leftover commas/spaces/case."""
    import re

    fillers = _HARD_FILLERS.get(lang)
    if not fillers:
        return text
    pattern = r"(?i)\b(?:" + "|".join(fillers) + r")\b[,.]?\s*"
    out = re.sub(pattern, "", text)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"^[,.\s]+", "", out)
    if out and out != text and out[0].islower():
        out = out[0].upper() + out[1:]  # sentence start after removing a filler
    return out or text


def _words(s: str) -> list[str]:
    import re
    return re.findall(r"[\wäöüß]+", s.lower())


def _sanitize(out: str, raw: str, lang: str) -> str | None:
    """Strip chatty preambles/quotes; reject output that lost too much content."""
    text = out.strip()
    # Drop a preamble line like "Here is the corrected text:" if present.
    if "\n" in text:
        first, rest = text.split("\n", 1)
        if any(m in first.lower() for m in _PREAMBLE_MARKERS) and rest.strip():
            text = rest.strip()
    text = text.strip().strip('"“”').strip()
    if not text or len(text) > len(raw) * 2 + 40:
        return None
    # Meaning guard: most content words of the input must survive.
    fillers = _FILLERS.get(lang, _FILLERS["en"])
    content = [w for w in raw.lower().replace(",", " ").split() if w not in fillers]
    if content:
        kept = sum(1 for w in content if w.rstrip(".?!") in text.lower())
        if kept / len(content) < 0.7:
            return None
    # Word-preservation guard: the model may only delete fillers and fix
    # punctuation/casing. Any word not present in the input means it rewrote
    # the text (e.g. de: "rausgegangen" -> "ausgegangen") — reject.
    raw_words = set(_words(raw))
    invented = [w for w in _words(text) if w not in raw_words]
    if invented:
        log.info("Cleanup altered words %s; keeping raw text", invented)
        return None
    return text


class Cleaner:
    """Serializes generations on one worker thread; times out to the raw text."""

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        from llama_cpp import Llama

        self.timeout = timeout
        t0 = time.perf_counter()
        log.info("Loading cleanup LLM %s...", model_path.name)
        import os

        # Benchmarked on i5-1235U: half the logical cores capped at 6 beats the
        # library default by ~65% (hybrid P/E-core scheduling penalty).
        n_threads = max(2, min(6, (os.cpu_count() or 4) // 2))
        self.llm = Llama(
            model_path=str(model_path),
            n_ctx=2048,
            n_threads=n_threads,
            n_gpu_layers=0,  # CPU on Windows; Metal wheels handle Mac
            verbose=False,
        )
        log.info("Cleanup LLM loaded in %.1fs", time.perf_counter() - t0)
        self._jobs: queue.Queue[tuple[str, queue.Queue]] = queue.Queue()
        self._busy = threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()

    def warm_up(self, lang: str = "en") -> None:
        """Pre-evaluate the few-shot prefix so the first dictation stays in budget."""
        if lang not in FEW_SHOT:
            lang = "en"
        self.clean("aufwärmen" if lang == "de" else "warm up",
                   lang=lang, timeout=30.0)
        log.info("Cleanup LLM warmed up (%s)", lang)

    def _worker(self) -> None:
        while True:
            text, lang, out = self._jobs.get()
            self._busy.set()
            try:
                result = self._generate(text, lang)
            except Exception:
                log.exception("Cleanup generation failed")
                result = None
            finally:
                self._busy.clear()
            out.put(result)

    def _generate(self, text: str, lang: str) -> str | None:
        # Bound output length: cleanup never legitimately doubles the input.
        max_tokens = max(32, int(len(text.split()) * 2.5) + 16)
        resp = self.llm.create_chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                *FEW_SHOT[lang],
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        out = resp["choices"][0]["message"]["content"]
        return _sanitize(out, text, lang)

    def clean(self, text: str, lang: str = "en", timeout: float | None = None) -> str:
        """Return cleaned text, or `text` unchanged on timeout/error/busy.

        Languages without few-shot examples pass through untouched.
        """
        if not text:
            return text
        text = strip_fillers(text, lang)  # deterministic, survives all fallbacks
        if lang not in FEW_SHOT:
            log.info("No cleanup examples for %r, using raw text", lang)
            return text
        if self._busy.is_set():
            log.warning("Cleanup LLM busy, using raw text")
            return text
        out: queue.Queue = queue.Queue(maxsize=1)
        self._jobs.put((text, lang, out))
        t0 = time.perf_counter()
        try:
            result = out.get(timeout=timeout or self.timeout)
        except queue.Empty:
            log.warning("Cleanup timed out after %.1fs, using raw text",
                        time.perf_counter() - t0)
            return text
        if result is None:
            return text
        log.info("Cleaned in %.2fs: %r", time.perf_counter() - t0, result)
        return result
