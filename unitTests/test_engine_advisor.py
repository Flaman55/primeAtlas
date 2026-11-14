"""engine_advisor proposes the engine of a run from its floor and width (time_model.py).

Checks:
- choose(): the fastest deterministic own engine wins unless pt1 with BPSW is faster by at
  least the offset (exactly at the offset -> pt1, just below -> the deterministic one);
  pt1 below the Miller-Rabin bound is deterministic and needs no offset; without a
  deterministic option pt1 is proposed; without options there is no proposal; an offset of
  1 proposes pt1 whenever it is not slower.
- advise() without a log: every own engine with a seed is estimated from the seed table and
  flagged estimated; low floor, narrow: v7; floor 30, 10^11 numbers: v7; floor 30, 10^9
  numbers: pt1 with the warning at the default offset, pt1-pss at offset 20; pt1-pss fits
  up to floor 34 and not on floor 35, where pt1 is proposed; a RAM check that rejects v7
  removes it; when no deterministic engine fits, pt1 is proposed for that reason.
- A calibration from the log (two rows) replaces the seed and clears the estimated flag.
- The guest (Pseudosquares, count mode): shown with its speed-up over the deterministic
  proposal only when the log calibrates it, it fits the floor and it is faster; never the
  proposal, even when it is the fastest of all; a log without its rows and an advisor
  without guests give the very same proposal.
- Floor or width changed there and back gives the same proposal.
- The run's start: no start is the floor's start (the same advice as start = 10^floor); a
  run starting higher on the floor takes longer (more sieving primes); on floor 24 pt1 from
  the floor's start stays below the Miller-Rabin bound (deterministic) and from 9 * 10^24
  reaches past it (probabilistic); pt1-pss fits by the run's real end; start there and back
  gives the same advice.
- advice_text(): the proposal names the engine, its time and reason, plus the estimated note
  for a seed estimate; the BPSW warning only for a probabilistic proposal; the guest line
  only with a guest, with its speed-up and what its count proves; no advice -> the no-proposal line.
- parse_offset(): a number >= 1 (decimals allowed), blank -> the default, anything else None.
- tools/engine_advice.py prints the proposal for a floor and width and exits 0.
Pure Python:
    python unitTests/test_engine_advisor.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

from primeatlas.generation import engine_advisor as ea  # noqa: E402
from primeatlas.generation import time_model as tm  # noqa: E402

W = tm.WINDOW_WIDTH
PT1, PSS, V7 = "pt1", "pt1-pss", "v7"
GUEST = "pseudosquares_count"


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def opt(engine, seconds, deterministic=True, estimated=False):
    return ea.Option(engine, seconds, deterministic, estimated)


def choose_case():
    passed = True
    pick = ea.choose([opt(V7, 100.0), opt(PT1, 50.0, False)], 3.0)
    passed &= check(pick.engine == V7 and pick.reason == ea.REASON_DETERMINISTIC
                    and pick.deterministic, f"pt1 only 2x faster -> v7 ({pick})")
    pick = ea.choose([opt(V7, 300.0), opt(PT1, 100.0, False)], 3.0)
    passed &= check(pick.engine == PT1 and pick.reason == ea.REASON_BPSW_FASTER
                    and not pick.deterministic and abs(pick.ratio - 3.0) < 1e-12
                    and pick.deterministic_engine == V7 and pick.deterministic_seconds == 300.0,
                    f"exactly at the offset -> pt1 with its ratio and the rival ({pick})")
    pick = ea.choose([opt(V7, 299.9), opt(PT1, 100.0, False)], 3.0)
    passed &= check(pick.engine == V7, "just below the offset -> v7")
    pick = ea.choose([opt(V7, 300.0), opt(PSS, 120.0), opt(PT1, 50.0, False)], 3.0)
    passed &= check(pick.engine == PSS, "the fastest deterministic is the reference: pt1-pss "
                    f"120 s vs pt1 50 s is under 3x ({pick.engine})")
    pick = ea.choose([opt(V7, 300.0), opt(PT1, 250.0, True)], 3.0)
    passed &= check(pick.engine == PT1 and pick.deterministic
                    and pick.reason == ea.REASON_DETERMINISTIC,
                    "pt1 below the bound is deterministic: fastest wins, no offset")
    pick = ea.choose([opt(PT1, 50.0, False)], 3.0)
    passed &= check(pick.engine == PT1 and pick.reason == ea.REASON_NO_DETERMINISTIC
                    and pick.deterministic_engine is None, "no deterministic option -> pt1")
    passed &= check(ea.choose([], 3.0) is None, "no options -> no proposal")
    pick = ea.choose([opt(V7, 100.0), opt(PT1, 100.0, False)], 1.0)
    passed &= check(pick.engine == PT1, "offset 1: pt1 when it is not slower")
    pick = ea.choose([opt(V7, 100.0), opt(PT1, 1e-6, False)], 1e12)
    passed &= check(pick.engine == V7, "a huge offset keeps the deterministic engine")
    return passed


def seeded(floor, windows, offset=ea.DEFAULT_BPSW_OFFSET, **kw):
    return ea.advise([], floor, windows, write_files=False, offset=offset, **kw)


def seed_case():
    passed = True
    advice = seeded(30, 100)
    engines = {o.engine for o in advice.options}
    passed &= check({V7, PSS, PT1} <= engines and all(o.estimated for o in advice.options),
                    f"no log: v7, pt1-pss and pt1 from the seed table, all estimated ({engines})")
    passed &= check(advice.estimated, "the proposal is flagged estimated")
    advice = seeded(15, 10)
    passed &= check(advice.engine == V7 and advice.deterministic,
                    f"floor 15, 10 windows -> v7 ({advice.engine})")
    advice = seeded(30, 10_000)
    passed &= check(advice.engine == V7, f"floor 30, 10^11 numbers -> v7 ({advice.engine})")
    advice = seeded(30, 100)
    passed &= check(advice.engine == PT1 and not advice.deterministic
                    and advice.reason == ea.REASON_BPSW_FASTER,
                    f"floor 30, 10^9 numbers, offset 3 -> pt1 with the warning ({advice.engine})")
    advice = seeded(30, 100, offset=20.0)
    passed &= check(advice.engine == PSS and advice.deterministic,
                    f"floor 30, 10^9 numbers, offset 20 -> pt1-pss ({advice.engine})")
    for floor in (33, 34):
        advice = seeded(floor, 100, offset=1e12)
        passed &= check(PSS in {o.engine for o in advice.options},
                        f"floor {floor}: pt1-pss fits (B raised for the proof)")
    advice = seeded(35, 100)
    passed &= check(PSS not in {o.engine for o in advice.options} and advice.engine == PT1,
                    f"floor 35: no pt1-pss, pt1 proposed ({advice.engine})")
    advice = seeded(30, 10_000, offset=20.0, ram_fits=lambda engine: engine != V7)
    passed &= check(V7 not in {o.engine for o in advice.options} and advice.engine == PSS,
                    f"RAM over budget removes v7 ({advice.engine})")
    advice = seeded(35, 100, offset=1e12, ram_fits=lambda engine: engine != V7)
    passed &= check(advice.engine == PT1 and advice.reason == ea.REASON_NO_DETERMINISTIC,
                    f"floor 35 without v7: pt1, no deterministic engine fits ({advice.reason})")
    return passed


def _rows(engine, floor, spans_seconds, version=""):
    return [tm.Sample(engine, floor, span, 10 ** floor + span, seconds, None, False, seconds,
                      version) for span, seconds in spans_seconds]


def calibration_case():
    passed = True
    rows = _rows(V7, 30, ((10 ** 9, 400.0), (10 ** 10, 430.0)))
    advice = ea.advise(rows, 30, 100, write_files=False)
    v7 = next(o for o in advice.options if o.engine == V7)
    cal = tm.calibrate(rows, V7)
    want = tm.estimate(cal, V7, 30, 100, False).run_seconds
    passed &= check(not v7.estimated and abs(v7.seconds - want) < 1e-6,
                    f"two logged v7 rows replace the seed ({v7.seconds:.1f} s vs {want:.1f} s)")
    seed = next(o for o in seeded(30, 100).options if o.engine == V7)
    passed &= check(abs(seed.seconds - v7.seconds) > 100, "and the time differs from the seed")
    return passed


def _guest_rows(rate_mn):
    return _rows(GUEST, 30, ((10 ** 9, 1e9 / (rate_mn * 1e6)), (10 ** 10, 1e10 / (rate_mn * 1e6))))


def guest_case():
    passed = True
    fast = _guest_rows(19.2)
    base = seeded(30, 100, offset=20.0)
    advice = ea.advise(fast, 30, 100, write_files=False, offset=20.0)
    passed &= check(advice.engine == base.engine == PSS, f"guest rows leave the proposal "
                    f"({advice.engine})")
    passed &= check(advice.guest is not None and advice.guest.engine == GUEST
                    and advice.guest.speedup > 1.0,
                    f"faster guest shown with its speed-up ({advice.guest})")
    if advice.guest is not None:
        pss = next(o for o in advice.options if o.engine == PSS)
        passed &= check(abs(advice.guest.speedup - pss.seconds / advice.guest.seconds) < 1e-9,
                        "speed-up = deterministic proposal time / guest time")
    passed &= check(GUEST not in {o.engine for o in advice.options},
                    "the guest is never among the options")
    blazing = _guest_rows(1e6)
    for offset in (3.0, 1e12):
        advice = ea.advise(blazing, 30, 100, write_files=False, offset=offset)
        passed &= check(advice.engine != GUEST and advice.engine == seeded(30, 100, offset).engine,
                        f"fastest guest never becomes the proposal (offset {offset:g})")
    without = ea.advise(fast, 30, 100, write_files=False, offset=20.0, guests=())
    passed &= check(without.guest is None and without.engine == base.engine
                    and without.seconds == base.seconds, "no guests: identical proposal")
    passed &= check(base.guest is None, "log without guest rows: no guest line")
    slow = _guest_rows(1.0)
    passed &= check(ea.advise(slow, 30, 100, write_files=False, offset=20.0).guest is None,
                    "slower guest: no guest line")
    high = _rows(GUEST, 34, ((10 ** 9, 50.0), (10 ** 10, 500.0)))
    passed &= check(ea.advise(high, 34, 100, write_files=False, offset=1e12).guest is None,
                    "guest past its last floor: no guest line")
    return passed


def there_and_back_case():
    passed = True
    first = seeded(30, 100)
    seeded(30, 10_000)
    seeded(25, 100)
    passed &= check(seeded(30, 100) == first, "width and floor there and back: same proposal")
    return passed


def text_case():
    from primeatlas.core.i18n import Translator
    from primeatlas.generation.engine_advice_text import advice_text
    T = Translator("en")
    passed = True
    duration = lambda s: f"{s:.0f} s"  # noqa: E731
    text = advice_text(seeded(30, 100), T, duration, 3.0)
    passed &= check(text.proposal.startswith("pt1, about 7 s") and "pt1-pss" in text.proposal
                    and "3x" in text.proposal and T("advisor.estimated") in text.proposal,
                    f"BPSW proposal: engine, time, rival, offset, estimated ({text.proposal!r})")
    passed &= check(text.warning == T("advisor.warning_bpsw") and not text.guest,
                    "BPSW proposal: warning, no guest")
    advice = ea.advise(_guest_rows(19.2), 30, 100, write_files=False, offset=20.0)
    text = advice_text(advice, T, duration, 20.0)
    passed &= check(text.proposal.startswith("pt1-pss") and not text.warning
                    and "1.2x" in text.guest and "pt1-pss" in text.guest
                    and "Benchmark" in text.guest and "proven" in text.guest,
                    f"deterministic proposal: no warning, guest line with its speed-up "
                    f"({text.guest!r})")
    text = advice_text(None, T, duration, 3.0)
    passed &= check(text == (T("advisor.none"), "", ""), "no advice -> the no-proposal line")
    return passed


def offset_case():
    passed = True
    passed &= check(ea.parse_offset("3") == 3.0 and ea.parse_offset(" 1.5 ") == 1.5,
                    "offset parses numbers")
    passed &= check(ea.parse_offset("") == ea.DEFAULT_BPSW_OFFSET
                    and ea.parse_offset(None) == ea.DEFAULT_BPSW_OFFSET, "blank -> default")
    passed &= check(all(ea.parse_offset(v) is None for v in ("0.5", "0", "-2", "abc", "nan",
                                                              "inf")),
                    "below 1, non-numbers and non-finite values are rejected")
    return passed


def cli_case():
    tool = os.path.join(ROOT, "tools", "engine_advice.py")
    proc = subprocess.run([sys.executable, tool, "--floor", "30", "--windows", "100",
                           "--offset", "20", "--log", os.path.join(ROOT, "no_such_log.csv")],
                          capture_output=True, text=True)
    passed = check(proc.returncode == 0 and "pt1-pss" in proc.stdout,
                   f"CLI proposes pt1-pss for floor 30, 100 windows, offset 20 "
                   f"(rc {proc.returncode}: {proc.stdout.strip()[:200]} {proc.stderr[-300:]})")
    proc = subprocess.run([sys.executable, tool, "--floor", "30", "--windows", "100",
                           "--log", os.path.join(ROOT, "no_such_log.csv")],
                          capture_output=True, text=True)
    passed &= check(proc.returncode == 0 and "pt1" in proc.stdout and "BPSW" in proc.stdout,
                    "CLI default offset: pt1 with the BPSW warning")
    return passed


def start_case():
    passed = True
    base = seeded(27, 100)
    passed &= check(ea.advise([], 27, 100, write_files=False, start=10 ** 27) == base,
                    "start = 10^floor gives the same advice as no start")
    high = ea.advise([], 27, 100, write_files=False, start=9 * 10 ** 27)
    low_s = {o.engine: o.seconds for o in base.options}
    high_s = {o.engine: o.seconds for o in high.options}
    passed &= check(high_s[V7] > low_s[V7],
                    f"v7 from 9 * 10^27 takes longer than from 10^27 ({high_s[V7]:.1f} > "
                    f"{low_s[V7]:.1f} s)")

    def pt1(start):
        advice = ea.advise([], 24, 100, write_files=False, offset=1e12, start=start)
        return {o.engine: o for o in advice.options}[PT1]

    passed &= check(pt1(None).deterministic, "floor 24 from its start: pt1 deterministic")
    passed &= check(not pt1(9 * 10 ** 24).deterministic,
                    "floor 24 from 9 * 10^24: pt1 past the Miller-Rabin bound, probabilistic")
    passed &= check(pt1(None).deterministic, "start back at the floor's start: deterministic again")
    for floor in (34,):
        top = ea.advise([], floor, 100, write_files=False, offset=1e12,
                        start=10 ** (floor + 1) - 100 * W)
        passed &= check(top is not None and PT1 in {o.engine for o in top.options},
                        f"floor {floor}, run at the floor's end: still planned")
    return passed


def main():
    passed = True
    for case in (choose_case, seed_case, calibration_case, guest_case, there_and_back_case,
                 start_case, text_case, offset_case, cli_case):
        passed &= case()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
