# ==============================================================================
# pattern_catalog_v1.py -- single source of truth for tracked k-tuple patterns.
#
# Used by:
#   - constellation_finder_v1.py (this folder) -- detection
#   - eventually an HTML portal generator -- report
#
# Source of records: https://pzktupel.de/x5.php (threshold "at least 25 digits", for
# k=6 threshold "at least 30 digits" -- the smallest threshold at which k=6 has a
# confirmed example). Maintained by Norman Luhn, Tony Forbes, and others.
#
# k=2..5: pzktupel.de does not track these patterns (too common, no "first discovery"
# worth recording) -- kept for continuity with twin/triplet/quadruplet/quintuplet
# detection. record_digits/discoverer/date are None for these (no reference point).
#
# k=6..21: 44 patterns taken directly from pzktupel.de/x5.php.
# ==============================================================================

PATTERN_CATALOG = [
    # --- k=2..5: not tracked by pzktupel.de, kept for continuity ---
    {"k": 2, "id": 1, "offsets": [0, 2], "record_digits": None, "discoverer": None, "date": None},
    {"k": 3, "id": 1, "offsets": [0, 2, 6], "record_digits": None, "discoverer": None, "date": None},
    {"k": 4, "id": 1, "offsets": [0, 2, 6, 8], "record_digits": None, "discoverer": None, "date": None},
    {"k": 5, "id": 1, "offsets": [0, 2, 6, 8, 12], "record_digits": None, "discoverer": None, "date": None},

    # --- k=6..21: from pzktupel.de/x5.php ---
    {"k": 6, "id": 1, "offsets": [0, 4, 6, 10, 12, 16], "record_digits": 30, "discoverer": "Tony Forbes", "date": "1993"},

    {"k": 7, "id": 1, "offsets": [0, 2, 6, 8, 12, 18, 20], "record_digits": 25, "discoverer": "Tony Forbes", "date": "1995"},
    {"k": 7, "id": 2, "offsets": [0, 2, 8, 12, 14, 18, 20], "record_digits": 25, "discoverer": "Tony Forbes", "date": "1995"},

    {"k": 8, "id": 1, "offsets": [0, 2, 6, 8, 12, 18, 20, 26], "record_digits": 25, "discoverer": "Tony Forbes", "date": "1995"},
    {"k": 8, "id": 2, "offsets": [0, 6, 8, 14, 18, 20, 24, 26], "record_digits": 26, "discoverer": "Tony Forbes", "date": "1993"},
    {"k": 8, "id": 3, "offsets": [0, 2, 6, 12, 14, 20, 24, 26], "record_digits": 51, "discoverer": "Tony Forbes", "date": "1994"},

    {"k": 9, "id": 1, "offsets": [0, 2, 6, 8, 12, 18, 20, 26, 30], "record_digits": 25, "discoverer": "Tony Forbes", "date": "1994"},
    {"k": 9, "id": 2, "offsets": [0, 2, 6, 12, 14, 20, 24, 26, 30], "record_digits": 25, "discoverer": "Tony Forbes", "date": "1996"},
    {"k": 9, "id": 3, "offsets": [0, 4, 6, 10, 16, 18, 24, 28, 30], "record_digits": 25, "discoverer": "Tony Forbes", "date": "1995"},
    {"k": 9, "id": 4, "offsets": [0, 4, 10, 12, 18, 22, 24, 28, 30], "record_digits": 25, "discoverer": "Tony Forbes", "date": "1995"},

    {"k": 10, "id": 1, "offsets": [0, 2, 6, 8, 12, 18, 20, 26, 30, 32], "record_digits": 30, "discoverer": "Tony Forbes", "date": "1994"},
    {"k": 10, "id": 2, "offsets": [0, 2, 6, 12, 14, 20, 24, 26, 30, 32], "record_digits": 25, "discoverer": "Tony Forbes", "date": "1995"},

    {"k": 11, "id": 1, "offsets": [0, 2, 6, 8, 12, 18, 20, 26, 30, 32, 36], "record_digits": 30, "discoverer": "Warut Roonguthai", "date": "11 Oct 1997"},
    {"k": 11, "id": 2, "offsets": [0, 4, 6, 10, 16, 18, 24, 28, 30, 34, 36], "record_digits": 56, "discoverer": "Michael Stocker", "date": "27 Jul 2013"},

    {"k": 12, "id": 1, "offsets": [0, 2, 6, 8, 12, 18, 20, 26, 30, 32, 36, 42], "record_digits": 27, "discoverer": "Arthur O. L. Atkin", "date": "10 Jun 1997"},
    {"k": 12, "id": 2, "offsets": [0, 6, 10, 12, 16, 22, 24, 30, 34, 36, 40, 42], "record_digits": 42, "discoverer": "Norman Luhn", "date": "05 Nov 2001"},

    {"k": 13, "id": 1, "offsets": [0, 2, 6, 8, 12, 18, 20, 26, 30, 32, 36, 42, 48], "record_digits": 30, "discoverer": "Waldvogel, Leikauf", "date": "23 Nov 2000"},
    {"k": 13, "id": 2, "offsets": [0, 4, 6, 10, 16, 18, 24, 28, 30, 34, 40, 46, 48], "record_digits": 33, "discoverer": "van Willegen, Andersen", "date": "19 Jan 2005"},
    {"k": 13, "id": 3, "offsets": [0, 2, 12, 14, 18, 20, 24, 30, 32, 38, 42, 44, 48], "record_digits": 61, "discoverer": "Norman Luhn", "date": "23 Mar 2017"},
    {"k": 13, "id": 4, "offsets": [0, 4, 6, 10, 16, 18, 24, 28, 30, 34, 36, 46, 48], "record_digits": 35, "discoverer": "Norman Luhn", "date": "5 Feb 2021"},
    {"k": 13, "id": 5, "offsets": [0, 2, 8, 14, 18, 20, 24, 30, 32, 38, 42, 44, 48], "record_digits": 27, "discoverer": "Tony Forbes", "date": "17 Feb 2000"},
    {"k": 13, "id": 6, "offsets": [0, 6, 12, 16, 18, 22, 28, 30, 36, 40, 42, 46, 48], "record_digits": 46, "discoverer": "Norman Luhn", "date": "28 Dec 2007"},

    {"k": 14, "id": 1, "offsets": [0, 2, 6, 8, 12, 18, 20, 26, 30, 32, 36, 42, 48, 50], "record_digits": 30, "discoverer": "Waldvogel, Leikauf", "date": "23 Nov 2000"},
    {"k": 14, "id": 2, "offsets": [0, 2, 8, 14, 18, 20, 24, 30, 32, 38, 42, 44, 48, 50], "record_digits": 46, "discoverer": "Norman Luhn", "date": "28 Dec 2007"},

    {"k": 15, "id": 1, "offsets": [0, 2, 6, 12, 14, 20, 26, 30, 32, 36, 42, 44, 50, 54, 56], "record_digits": 28, "discoverer": "Felicity, Tony Forbes", "date": "19 Oct 2008"},
    {"k": 15, "id": 2, "offsets": [0, 2, 6, 8, 12, 18, 20, 26, 30, 32, 36, 42, 48, 50, 56], "record_digits": 30, "discoverer": "Waldvogel, Leikauf", "date": "23 Nov 2000"},
    {"k": 15, "id": 3, "offsets": [0, 2, 6, 12, 14, 20, 24, 26, 30, 36, 42, 44, 50, 54, 56], "record_digits": 29, "discoverer": "Audrey, Tony Forbes", "date": "9 Oct 2008"},
    {"k": 15, "id": 4, "offsets": [0, 6, 8, 14, 20, 24, 26, 30, 36, 38, 44, 48, 50, 54, 56], "record_digits": 25, "discoverer": "Norman Luhn", "date": "26 Dec 2018"},

    {"k": 16, "id": 1, "offsets": [0, 2, 6, 12, 14, 20, 26, 30, 32, 36, 42, 44, 50, 54, 56, 60], "record_digits": 25, "discoverer": "Jaroslaw Wroblewski", "date": "14 Dec 2008"},
    {"k": 16, "id": 2, "offsets": [0, 4, 6, 10, 16, 18, 24, 28, 30, 34, 40, 46, 48, 54, 58, 60], "record_digits": 25, "discoverer": "Jaroslaw Wroblewski", "date": "14 Dec 2008"},

    {"k": 17, "id": 1, "offsets": [0, 6, 8, 12, 18, 20, 26, 32, 36, 38, 42, 48, 50, 56, 60, 62, 66], "record_digits": 25, "discoverer": "Jaroslaw Wroblewski", "date": "14 Dec 2008"},
    {"k": 17, "id": 2, "offsets": [0, 2, 6, 12, 14, 20, 24, 26, 30, 36, 42, 44, 50, 54, 56, 62, 66], "record_digits": 26, "discoverer": "Jaroslaw Wroblewski", "date": "14 Dec 2008"},
    {"k": 17, "id": 3, "offsets": [0, 4, 6, 10, 16, 18, 24, 28, 30, 34, 40, 46, 48, 54, 58, 60, 66], "record_digits": 25, "discoverer": "Jaroslaw Wroblewski", "date": "14 Dec 2008"},
    {"k": 17, "id": 4, "offsets": [0, 4, 10, 12, 16, 22, 24, 30, 36, 40, 42, 46, 52, 54, 60, 64, 66], "record_digits": 25, "discoverer": "Jaroslaw Wroblewski", "date": "14 Dec 2008"},

    {"k": 18, "id": 1, "offsets": [0, 4, 6, 10, 16, 18, 24, 28, 30, 34, 40, 46, 48, 54, 58, 60, 66, 70], "record_digits": 25, "discoverer": "Waldvogel, Leikauf", "date": "31 Jan 2001"},
    {"k": 18, "id": 2, "offsets": [0, 4, 10, 12, 16, 22, 24, 30, 36, 40, 42, 46, 52, 54, 60, 64, 66, 70], "record_digits": 25, "discoverer": "Waldvogel, Leikauf", "date": "13 Nov 2000"},

    {"k": 19, "id": 1, "offsets": [0, 4, 6, 10, 16, 22, 24, 30, 34, 36, 42, 46, 52, 60, 64, 66, 70, 72, 76], "record_digits": 29, "discoverer": "Chermoni, Wroblewski", "date": "8 Jan 2015"},
    {"k": 19, "id": 2, "offsets": [0, 4, 6, 10, 12, 16, 24, 30, 34, 40, 42, 46, 52, 54, 60, 66, 70, 72, 76], "record_digits": 30, "discoverer": "Chermoni, Wroblewski", "date": "27 Dec 2018"},
    {"k": 19, "id": 3, "offsets": [0, 4, 6, 10, 16, 18, 24, 28, 30, 34, 40, 46, 48, 54, 58, 60, 66, 70, 76], "record_digits": 27, "discoverer": "John Armitage", "date": "24 Apr 2026"},
    {"k": 19, "id": 4, "offsets": [0, 6, 10, 16, 18, 22, 28, 30, 36, 42, 46, 48, 52, 58, 60, 66, 70, 72, 76], "record_digits": 27, "discoverer": "Chermoni, Wroblewski", "date": "9 Feb 2011"},

    {"k": 20, "id": 1, "offsets": [0, 2, 6, 8, 12, 20, 26, 30, 36, 38, 42, 48, 50, 56, 62, 66, 68, 72, 78, 80], "record_digits": 30, "discoverer": "Chermoni, Wroblewski", "date": "6 Oct 2014"},
    {"k": 20, "id": 2, "offsets": [0, 2, 8, 12, 14, 18, 24, 30, 32, 38, 42, 44, 50, 54, 60, 68, 72, 74, 78, 80], "record_digits": 28, "discoverer": "Chermoni, Wroblewski", "date": "24 Jun 2014"},

    {"k": 21, "id": 1, "offsets": [0, 4, 6, 10, 12, 16, 24, 30, 34, 40, 42, 46, 52, 54, 60, 66, 70, 72, 76, 82, 84], "record_digits": 30, "discoverer": "Chermoni, Wroblewski", "date": "27 Dec 2018"},
    {"k": 21, "id": 2, "offsets": [0, 2, 8, 12, 14, 18, 24, 30, 32, 38, 42, 44, 50, 54, 60, 68, 72, 74, 78, 80, 84], "record_digits": 29, "discoverer": "Chermoni, Wroblewski", "date": "8 Jan 2015"},
]


def patterns_for_k(k):
    """Returns catalog entries for a given k, sorted by id."""
    return sorted([w for w in PATTERN_CATALOG if w["k"] == k], key=lambda w: w["id"])


def all_k():
    """Returns the sorted list of every k present in the catalog."""
    return sorted(set(w["k"] for w in PATTERN_CATALOG))


def find_pattern(k, offsets):
    """Tries to match (k, offset list) to a specific catalog entry. Returns the entry
    (dict) or None if there's no match (an uncatalogued layout)."""
    for w in PATTERN_CATALOG:
        if w["k"] == k and w["offsets"] == list(offsets):
            return w
    return None
