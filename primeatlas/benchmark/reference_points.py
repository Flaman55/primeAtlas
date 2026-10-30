"""Reference throughput of well-known prime tools, drawn on the Benchmark tab's n/s chart.

Values are copied from published results or from the project's own benchmark of
2026-10-29 (BENCHMARK.md), not computed by the app. Each Reference keeps its source and the
conditions it was measured under; hardware, thread count and what is measured (counting,
iterating, sieving) differ between entries and from a PrimeAtlas run, so the points are an
order-of-magnitude reference, not a like-for-like comparison.

points: (base_exponent, numbers per second) -- numbers of the range divided by seconds.
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
    Reference(
        "primesieve 12.6, count 2..10^13, Ryzen 9 9900X", "primesieve PTS", "public",
        "OpenBenchmarking.org pts/primesieve, length 1e13, 97 s (retrieved 2026-10-30): "
        "https://openbenchmarking.org/test/pts/primesieve",
        "#7b2d8e",
        ((13, 1e13 / 97),)),
    Reference(
        "primesieve 12.15, 24 threads, count 10^10 numbers, Ryzen 9 5900X", "primesieve",
        "own",
        "PrimeAtlas benchmark 2026-10-29, series A (BENCHMARK.md): primesieve's own "
        "reported seconds, 0.10 / 0.22 / 0.69 / 3.0 s",
        "#00d0d0",
        ((10, 1e10 / 0.10), (13, 1e10 / 0.22), (16, 1e10 / 0.69), (19, 1e10 / 3.0))),
)


def reference_series(translator_t):
    """[Series] for every reference, dashed; the legend shows the short tag and the kind
    label, the full name and source stay in REFERENCES (PDF footnote)."""
    kind_keys = {"public": "bench.ref_public", "own": "bench.ref_own"}
    return [Series(f"{ref.tag} ({translator_t(kind_keys[ref.kind])})", ref.tag,
                   list(ref.points), ref.color, True)
            for ref in REFERENCES]
