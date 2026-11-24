"""
test_ring_viz_pattern_offsets.py -- a line-mode k-tuple pattern given by its offsets (the
Rings tab's catalog list): line_geometry.is_admissible, the anchor without a seed
(resolve_pattern_anchor(None, ...)) and the renderer's --pattern-offsets flag (parsing,
every rejected shape or combination, LineMode.prepare_launch). The seed-derived pattern and
the rest of line mode are in test_ring_viz_pattern_mode.py. No moderngl/glfw import.

Usage: python unitTests\test_ring_viz_pattern_offsets.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_is_admissible():
    """A pattern is admissible when no prime p <= k has every residue mod p hit by an
    offset; every catalog pattern and every seed-built pattern is."""
    import pattern_catalog_v1
    from primeatlas.visualization.rings.line.line_geometry import (
        is_admissible, pattern_offsets_from_seed,
    )

    check(all(is_admissible(w["offsets"]) for w in pattern_catalog_v1.PATTERN_CATALOG),
          "every catalog pattern is admissible")
    check(all(is_admissible(pattern_offsets_from_seed(k, 101)) for k in range(2, 22)),
          "seed-built patterns from a p0 above k are admissible")
    # A seed at or below k can include a small prime as a member: 5,7,11,13,17,19,23
    # covers every residue mod 5 (the founding coincidence pattern_wheel_residues names).
    check(not is_admissible(pattern_offsets_from_seed(7, 5)), "k=7 from p0=5 is inadmissible")
    check(not is_admissible([0, 2, 4]), "[0, 2, 4] covers every residue mod 3 -> inadmissible")
    check(not is_admissible([0, 1]), "[0, 1] covers every residue mod 2 -> inadmissible")
    check(is_admissible([0, 2]) and is_admissible([0, 4]), "twins and cousins are admissible")
    # p = 17 and 19 matter for k >= 17 (the default wheel stops at 13).
    covers_17 = list(range(0, 34, 2))  # 17 offsets 0..32: every residue mod 17
    check(not is_admissible(covers_17), "17 offsets covering every residue mod 17 -> inadmissible")


def _test_resolve_pattern_anchor_without_seed():
    """With no seed prime (a pattern from the catalog) the anchor is the first
    wheel-compatible candidate at or past the window's lower edge."""
    from primeatlas.visualization.rings.line.line_geometry import (
        resolve_pattern_anchor, pattern_wheel_residues,
    )

    for offsets, lo in (([0, 2], 2), ([0, 2, 6, 8], 2), ([0, 2, 6, 8], 10**12 + 7), ([0, 4, 6, 10, 12, 16], 1000)):
        modulus, residues = pattern_wheel_residues(offsets)
        anchor = resolve_pattern_anchor(None, offsets, lo, lo + 10**6)
        check(anchor >= lo and anchor % modulus in residues
              and not any(n % modulus in residues for n in range(lo, anchor)),
              f"{offsets} from {lo}: first wheel candidate (got {anchor})")


def _parse_cli(argv):
    """renderer_cli.parse_args on argv; (args, None) or (None, the error text)."""
    import contextlib
    import io
    from primeatlas.visualization.shared import renderer_cli

    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return renderer_cli.parse_args("test", argv), None
    except SystemExit:
        return None, err.getvalue()


def _test_pattern_offsets_cli():
    """--pattern-offsets: a comma-separated catalog pattern for line mode; every bad
    combination or shape fails with a readable message."""
    import types
    import numpy as np
    from primeatlas.visualization.rings.line.line_mode import LineMode
    from primeatlas.visualization.rings.line.line_geometry import resolve_pattern_anchor

    line = ["--viz-mode", "line", "--load-range", "100,1000"]
    args, err = _parse_cli(line + ["--pattern-offsets", "0,2,6,8"])
    check(args is not None and args.pattern_offsets == [0, 2, 6, 8],
          f"--pattern-offsets 0,2,6,8 -> [0, 2, 6, 8] (err={err!r})")
    args, err = _parse_cli(line + ["--pattern-offsets", "0, 4, 6, 10, 12, 16"])
    check(args is not None and args.pattern_offsets == [0, 4, 6, 10, 12, 16], "spaces after commas parse")
    args, err = _parse_cli(line)
    check(args is not None and args.pattern_offsets is None, "no flag -> None")

    bad = {
        "without line mode": ["--load-range", "100,1000", "--pattern-offsets", "0,2"],
        "with the seed flags": line + ["--pattern-offsets", "0,2", "--pattern-seed-k", "2",
                                       "--pattern-seed-start", "5"],
        "one value": line + ["--pattern-offsets", "0"],
        "first not 0": line + ["--pattern-offsets", "2,4"],
        "not ascending": line + ["--pattern-offsets", "0,6,2"],
        "repeated": line + ["--pattern-offsets", "0,2,2"],
        "inadmissible": line + ["--pattern-offsets", "0,2,4"],
        "not a number": line + ["--pattern-offsets", "0,x"],
    }
    for label, argv in bad.items():
        args, err = _parse_cli(argv)
        check(args is None and "--pattern-offsets" in (err or ""),
              f"--pattern-offsets {label} -> error naming the flag (got {err!r})")

    # prepare_launch: the catalog pattern drives the session; the anchor is the first
    # wheel candidate in the window (no seed occurrence to start from).
    args, _err = _parse_cli(line + ["--pattern-offsets", "0,2,6,8"])
    primes = np.array([p for p in range(101, 1000) if all(p % d for d in range(2, int(p ** 0.5) + 1))])
    launch = types.SimpleNamespace(range_mode=True, range_primes=primes, n=100)
    config = LineMode.prepare_launch(args, launch)
    check(config["pattern_offsets"] == [0, 2, 6, 8], "prepare_launch passes the offsets on")
    want = resolve_pattern_anchor(None, [0, 2, 6, 8], int(primes[0]), int(primes[-1]) - 8)
    check(launch.n == want, f"anchor = first wheel candidate in the window (got {launch.n}, want {want})")

    # The seed path is unchanged.
    args, _err = _parse_cli(line + ["--pattern-seed-k", "4", "--pattern-seed-start", "101"])
    launch = types.SimpleNamespace(range_mode=True, range_primes=primes, n=100)
    config = LineMode.prepare_launch(args, launch)
    check(config["pattern_offsets"] == [0, 2, 6, 8] and launch.n == 101,
          f"seed k=4 p0=101 -> [0, 2, 6, 8] anchored at 101 (got {config['pattern_offsets']}, {launch.n})")



def main():
    _test_is_admissible()
    _test_resolve_pattern_anchor_without_seed()
    _test_pattern_offsets_cli()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
