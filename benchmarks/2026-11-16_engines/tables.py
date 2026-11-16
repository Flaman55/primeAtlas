"""
tables.py -- the Markdown tables of the 2026-11-16 series, computed from results.csv.

Speed is numbers / (total_seconds - write_seconds): the whole run except the phase that
writes the windows, so that the Atlas engines and the Pseudosquares Prime Sieve (count mode,
nothing written) are timed alike, and the speed does not depend on the disk. Each point is
the mean of its two runs; the spread is (max - min) / mean of those runs.

Usage: python3 tables.py [results.csv]
"""
import csv
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    speed, peak, write = defaultdict(list), defaultdict(list), defaultdict(list)
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r["returncode"] != "0":
                continue
            n = int(r["numbers"])
            t = float(r["total_seconds"])
            w = float(r["write_seconds"] or 0)
            key = (r["engine"], int(r["floor"]), n)
            speed[key].append(n / (t - w) / 1e6)
            peak[key].append(float(r["peak_pss_mb"]) / 1024)
            write[key].append(w)
    return speed, peak, write


def mean(v):
    return sum(v) / len(v)


def spread(v):
    return (max(v) - min(v)) / mean(v) * 100 if len(v) > 1 else 0.0


def fmt(v):
    m = mean(v)
    return f"{m:,.0f}" if m >= 100 else f"{m:.1f}"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "results.csv")
    speed, peak, write = load(path)

    print("### v7.4, v7.2 and the Pseudosquares Prime Sieve (M numbers/s)\n")
    print("| floor | PSS 10^9 | v7.4 10^9 | v7.4 10^10 | v7.4 10^11 | v7.2 10^11 | v7.4 / v7.2 at 10^11 |")
    print("|---|---|---|---|---|---|---|")
    for f in range(18, 31):
        row = [fmt(speed[("pss", f, 10 ** 9)])]
        for n in (10 ** 9, 10 ** 10, 10 ** 11):
            row.append(fmt(speed[("v7", f, n)]))
        row.append(fmt(speed[("v7.2", f, 10 ** 11)]))
        ratio = mean(speed[("v7", f, 10 ** 11)]) / mean(speed[("v7.2", f, 10 ** 11)])
        row.append(f"{ratio:.2f}")
        print(f"| {f} | " + " | ".join(row) + " |")

    print("\n### pt1 and pt1-pss, 10^9 numbers (M numbers/s)\n")
    print("| floor | pt1 (P, BPSW) | pt1-pss (proved) |")
    print("|---|---|---|")
    for f in range(30, 36):
        a = fmt(speed[("pt1", f, 10 ** 9)])
        k = ("pt1-pss", f, 10 ** 9)
        b = fmt(speed[k]) if k in speed else "refuses floors 35-37"
        print(f"| {f} | {a} | {b} |")

    print("\n### Peak RAM, largest over the floors (GB, PSS of the process tree)\n")
    print("| engine | 10^9 | 10^10 | 10^11 |")
    print("|---|---|---|---|")
    for e in ("v7", "v7.2", "pss", "pt1", "pt1-pss"):
        cells = []
        for n in (10 ** 9, 10 ** 10, 10 ** 11):
            vals = [x for (ee, f, nn), v in peak.items() if ee == e and nn == n for x in v]
            cells.append(f"{max(vals):.1f}" if vals else "")
        print(f"| {e} | " + " | ".join(cells) + " |")

    print("\n### Spread above 2 % (two runs of one point)\n")
    print("| engine | floor | numbers | spread % | mean seconds without write |")
    print("|---|---|---|---|---|")
    for (e, f, n), v in sorted(speed.items(), key=lambda x: (x[0][2], x[0][0], x[0][1])):
        if spread(v) > 2:
            wall = n / 1e6 / mean(v)
            print(f"| {e} | {f} | 10^{len(str(n)) - 1} | {spread(v):.1f} | {wall:.1f} |")

    w11 = [x for (e, f, n), v in write.items() if n == 10 ** 11 for x in v]
    print(f"\nWrite phase at 10^11 numbers, scratch storage on /mnt/h: "
          f"{min(w11):.1f}-{max(w11):.1f} s per run (not included above).")


if __name__ == "__main__":
    main()
