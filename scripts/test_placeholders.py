from collections import Counter
import unittest

from build import placeholders


class PlaceholderTests(unittest.TestCase):
    def test_percentages_in_prose(self):
        samples = [
            "25% likely; 25% im Gefängnis",
            "25%-Chance",
            "100%ig sicher",
            "Chance: 25%.",
        ]

        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(placeholders(sample), Counter())

    def test_real_placeholders(self):
        tokens = ["%1", "%2", "%s", "%d", "% d", "%.2f", "{0}", "{name}"]
        self.assertEqual(placeholders(" / ".join(tokens)), Counter(tokens))
        self.assertEqual(placeholders("1%s"), Counter({"%s": 1}))

    def test_missing_placeholder_is_detected(self):
        self.assertNotEqual(placeholders("25% likely: %1"), placeholders("25% wahrscheinlich"))


if __name__ == "__main__":
    unittest.main()
