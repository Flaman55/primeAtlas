"""Wrapping a table heading to its column (primeatlas/core/heading_wrap.py).

wrap(): words greedily on lines no wider than the width; a word wider than the width alone on
its line; blank text no lines. min_width(): the narrowest width at which the text wraps into at
most max_lines lines; never wider than the text on one line, never narrower than its widest
word, and wrap() at it really gives at most max_lines lines. fit_width(): the column width, the
wider of the widest cell and the heading's min_width, plus the padding. Measured with a fake
font (one unit per character), so pure:
    python unitTests/test_heading_wrap.py
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.core import heading_wrap as hw  # noqa: E402


def measure(text):
    return len(text)


class HeadingWrapTests(unittest.TestCase):

    def test_wrap(self):
        self.assertEqual(hw.wrap("Run n/s without verify", 12, measure),
                         ["Run n/s", "without", "verify"])
        self.assertEqual(hw.wrap("Run n/s without verify", 100, measure),
                         ["Run n/s without verify"])
        self.assertEqual(hw.wrap("Superlongword ab", 4, measure), ["Superlongword", "ab"])
        self.assertEqual(hw.wrap("  ", 10, measure), [])
        self.assertEqual(hw.wrap("a\nb c", 10, measure), ["a", "b c"], "a newline breaks")

    def test_min_width(self):
        for text in ("Run n/s without verify", "Sieve n/s", "Peak RAM [MB]", "Engine",
                     "Spadek przez weryfikację", "a bb ccc dddd eeeee", "☑ Kopiuj"):
            width = hw.min_width(text, measure)
            words = text.split()
            self.assertLessEqual(width, measure(text), text)
            self.assertGreaterEqual(width, max(map(measure, words)), text)
            self.assertLessEqual(len(hw.wrap(text, width, measure)), 2, text)
            if width > max(map(measure, words)):
                self.assertGreater(len(hw.wrap(text, width - 1, measure)), 2,
                                   f"{text}: the narrowest such width")
        self.assertEqual(hw.min_width("Run n/s without verify", measure), 14)
        self.assertEqual(hw.min_width("Engine", measure), 6, "one word: its width")
        self.assertEqual(hw.min_width("", measure), 0)
        self.assertEqual(hw.min_width("a b c d", measure, max_lines=4), 1)

    def test_fit_width(self):
        self.assertEqual(hw.fit_width("Run n/s without verify", ["123", "4,567"], measure, 10),
                         14 + 10, "heading wider than the cells: its two-line width")
        self.assertEqual(hw.fit_width("Run", ["1,234,567,890"], measure, 10), 13 + 10,
                         "cells wider: the widest cell")
        self.assertEqual(hw.fit_width("Run", [], measure, 10), 3 + 10)


if __name__ == "__main__":
    unittest.main()
