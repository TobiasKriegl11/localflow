"""Fast, dependency-free tests for the auto-language decision logic.

These lock the behaviour of the pure helpers extracted from `_auto_take` so the
language-switching logic (reworked twice now) can't silently regress. They need
neither the whisper model nor audio — run with:  python -m unittest discover tests
"""

import types
import unittest

from localflow.transcribe import Transcriber, SWITCH_DET_PROB

HI = SWITCH_DET_PROB + 0.15   # a clearly-confident detection (~0.85)
LO = SWITCH_DET_PROB - 0.09   # the "Ja."-style fluke (~0.61)


class ChooseLanguage(unittest.TestCase):
    choose = staticmethod(Transcriber._choose_language)

    def test_keeps_anchor_when_detection_agrees(self):
        self.assertEqual(self.choose("de", HI, "de", "de"), "de")

    def test_keeps_anchor_on_unsure_disagreement(self):
        # The bug this whole rework exists to kill: a short "Ja." heard as en@0.61
        # must NOT flip a German session.
        self.assertEqual(self.choose("en", LO, "de", "de"), "de")

    def test_switches_on_confident_disagreement(self):
        self.assertEqual(self.choose("en", HI, "de", "de"), "en")

    def test_threshold_is_inclusive(self):
        self.assertEqual(self.choose("en", SWITCH_DET_PROB, "de", "de"), "en")
        self.assertEqual(self.choose("en", SWITCH_DET_PROB - 0.001, "de", "de"), "de")

    def test_no_anchor_confident_takes_detection(self):
        self.assertEqual(self.choose("en", HI, "", "de"), "en")

    def test_no_anchor_unsure_takes_fallback_not_detection(self):
        # Finding #1: a first/anchorless take that is unsure must not let a short
        # ambiguous detection set (and later persist) the session language.
        self.assertEqual(self.choose("en", LO, "", "de"), "de")


class RankedAllowed(unittest.TestCase):
    rank = staticmethod(Transcriber._ranked_allowed)

    def test_sorts_descending(self):
        out = self.rank([("de", 0.2), ("en", 0.7)], [])
        self.assertEqual(out[0], ("en", 0.7))

    def test_restricts_to_allowed(self):
        out = self.rank([("fr", 0.9), ("de", 0.05), ("en", 0.05)], ["de", "en"])
        self.assertTrue(all(lang in ("de", "en") for lang, _ in out))
        self.assertEqual(out[0][0], "de")

    def test_never_leaks_disallowed_language(self):
        # Finding #2: when nothing in the detection is allowed (e.g. the fabricated
        # single-entry fallback), return allowed langs at zero confidence.
        out = self.rank([("fr", 1.0)], ["de", "en"])
        self.assertEqual([lang for lang, _ in out], ["de", "en"])
        self.assertEqual(out[0][1], 0.0)


class FallbackLang(unittest.TestCase):
    def _fb(self, last, det, allowed):
        ns = types.SimpleNamespace(last_language=last)
        return Transcriber._fallback_lang(ns, det, allowed)

    def test_prefers_last_language_when_allowed(self):
        self.assertEqual(self._fb("de", "en", ["de", "en"]), "de")

    def test_ignores_last_language_outside_allowed(self):
        self.assertEqual(self._fb("fr", "en", ["de", "en"]), "de")

    def test_falls_back_to_first_allowed_when_no_last(self):
        self.assertEqual(self._fb("", "en", ["de", "en"]), "de")

    def test_uses_detection_when_nothing_else(self):
        self.assertEqual(self._fb("", "en", []), "en")


if __name__ == "__main__":
    unittest.main()
