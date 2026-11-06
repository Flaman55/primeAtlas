"""Reference throughput of PARI/GP, drawn on the Benchmark tab's sieve n/s chart.

Values are copied from published results, not computed by the app. Each Reference keeps
its source and the conditions it was measured under; hardware, thread count and range differ
from a PrimeAtlas run, so the points are an order-of-magnitude reference, not a like-for-like
comparison.

points: (base_exponent, numbers per second) -- numbers of the range divided by seconds.
No primesieve entry: Atlas measures the primesieve program itself on the requested range
(primesieve mode, Native), which compares on equal ranges and thread counts.
kind: "public" (published by the tool's authors or a public result database) or "own"
(measured on the reference desktop, Ryzen 9 5900X, with the published tool).
"""
from collections import namedtuple

from .chart_series import Series

Reference = namedtuple("Reference", "name tag kind source color points")


def _pari_forprime_seconds_per_1e9(floor):
    # Zakharevich's fit for stock forprime (nextprime-based) for N >> 10^19.
    return 0.025 * floor ** 2.5 + 310


REFERENCES = (
    Reference(
        "PARI/GP forprime, 1 thread, Core i5-13500T", "PARI forprime", "public",
        "I. Zakharevich, pari-dev, 2024-09: "
        "https://pari.math.u-bordeaux.fr/archives/pari-dev-2409/msg00016.html",
        "#d62728",
        tuple((floor, 1e9 / _pari_forprime_seconds_per_1e9(floor)) for floor in range(19, 28))),
    Reference(
        "PARI/GP sieving patch (pre-alpha), 110 GB prime table", "PARI sieve patch", "public",
        "I. Zakharevich, pari-dev, 2024-09 (11.3 s per 10^9 up to 10^25, sieving primes "
        "prepared beforehand): "
        "https://pari.math.u-bordeaux.fr/archives/pari-dev-2409/msg00016.html",
        "#e7298a",
        ((25, 1e9 / 11.3),)),
)


def reference_series(translator_t):
    """[Series] for every reference, dashed; the legend shows the short tag and the kind
    label, the full name and source stay in REFERENCES (PDF footnote)."""
    kind_keys = {"public": "bench.ref_public", "own": "bench.ref_own"}
    return [Series(f"{ref.tag} ({translator_t(kind_keys[ref.kind])})", ref.tag,
                   list(ref.points), ref.color, True)
            for ref in REFERENCES]
