"""End-to-end language-switching tests on synthesized speech.

Whisper's own language detection is the signal `_auto_take` trusts, so the only
faithful regression test drives real audio through it. We synthesize German and
English clips with the Windows SAPI voices (Hedda de-DE / Zira en-US), then run
session scenarios and assert there is no mid-session flapping while genuine
switches are still caught.

Heavy and platform-bound, so it self-skips unless all of these are present:
Windows, the faster-whisper base model under models/, and both SAPI voices.
Clips are cached under tests/_tts_cache/ (git-ignored) so reruns are fast.

    python -m unittest tests.test_language_e2e
"""

import os
import subprocess
import sys
import unittest
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "faster-whisper-base"
CACHE = Path(__file__).resolve().parent / "_tts_cache"
GEN = Path(__file__).resolve().parent / "gen_tts.ps1"
N_PER_LANG = 12  # gen_tts.ps1 emits de_00..de_11 / en_00..en_11


def _voices_available() -> bool:
    ps = ("Add-Type -AssemblyName System.Speech;"
          "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
          ".GetInstalledVoices().VoiceInfo.Name -join ';'")
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return False
    return "Hedda" in out and "Zira" in out


def _requirements_met() -> bool:
    if sys.platform != "win32" or not MODEL.exists():
        return False
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    return GEN.exists() and _voices_available()


def _ensure_clips() -> None:
    have = all((CACHE / f"{lang}_{i:02d}.wav").exists()
               for lang in ("de", "en") for i in range(N_PER_LANG))
    if have:
        return
    CACHE.mkdir(exist_ok=True)
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(GEN), "-OutDir", str(CACHE)],
                   check=True, capture_output=True, text=True, timeout=300)


def _load(name: str) -> np.ndarray:
    with wave.open(str(CACHE / name), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


@unittest.skipUnless(_requirements_met(),
                     "needs Windows + faster-whisper base model + Hedda/Zira voices")
class LanguageSwitchingE2E(unittest.TestCase):
    tr = None

    @classmethod
    def setUpClass(cls):
        _ensure_clips()
        from localflow.transcribe import Transcriber
        cls.tr = Transcriber(model_name=str(MODEL))

    def _run(self, order, anchor):
        """Return (mislabels, spurious_switches) for a scripted session."""
        self.tr.current_language = anchor
        self.tr.last_language = anchor or "en"
        mislabels = switches = 0
        prev = None
        for name, expect in order:
            _, lang = self.tr.transcribe_take(_load(name), language="auto",
                                              allowed_languages=["de", "en"])
            mislabels += (lang != expect)
            switches += (prev is not None and lang != prev)
            prev = lang
        return mislabels, switches

    def _de(self, i): return (f"de_{i:02d}.wav", "de")
    def _en(self, i): return (f"en_{i:02d}.wav", "en")

    def test_pure_german_never_flaps(self):
        # Includes de_07 ("Ja.", ~1.2s) that used to flip to English.
        mis, sw = self._run([self._de(i) for i in range(N_PER_LANG)], "de")
        self.assertEqual((mis, sw), (0, 0))

    def test_pure_english_never_flaps(self):
        mis, sw = self._run([self._en(i) for i in range(N_PER_LANG)], "en")
        self.assertEqual((mis, sw), (0, 0))

    def test_switches_and_returns(self):
        order = [self._de(0), self._de(1), self._en(1), self._en(2),
                 self._de(3), self._de(4)]
        mis, _ = self._run(order, "de")
        self.assertEqual(mis, 0)

    def test_sustained_switch_stays(self):
        order = [self._de(0), self._en(1), self._en(2), self._en(5), self._en(11)]
        mis, sw = self._run(order, "de")
        self.assertEqual(mis, 0)
        self.assertEqual(sw, 1)  # exactly one de->en transition, then stable

    def test_genuine_alternation(self):
        order = [self._de(1), self._en(1), self._de(3), self._en(3),
                 self._de(5), self._en(5)]
        mis, _ = self._run(order, "de")
        self.assertEqual(mis, 0)


if __name__ == "__main__":
    unittest.main()
