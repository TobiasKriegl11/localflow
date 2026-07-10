"""Guard the config defaults that a bilingual user depends on.

The original "mixes English with German" bug was a *default*: language was
seeded from the OS UI locale, which silently forced a single language and
disabled detection. These tests pin the corrected defaults so that can't
regress. No model or audio needed.
"""

import unittest

from localflow.config import Settings


class Defaults(unittest.TestCase):
    def test_language_defaults_to_auto(self):
        # Must NOT depend on OS locale — auto is what enables detection.
        self.assertEqual(Settings().language, "auto")

    def test_high_accuracy_off_by_default(self):
        # Opt-in: small is slower and may need a download.
        self.assertFalse(Settings().high_accuracy)

    def test_auto_languages_default_de_en(self):
        self.assertEqual(Settings().auto_languages, ["de", "en"])


if __name__ == "__main__":
    unittest.main()
