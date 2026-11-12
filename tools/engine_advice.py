"""
engine_advice.py -- prints the engine the advisor proposes for one run (engine_advisor.py),
the same proposal the Generation tab shows, with every option's estimated time.

    python tools/engine_advice.py --floor 30 --windows 100 [--offset 3] [--write-files]
        [--pt1-b 0] [--log <storage folder>/benchmark_log.csv]

--windows is the run width in windows of 10^7; --offset is how many times faster pt1 with
BPSW must be than the fastest deterministic engine (default 3, arbitrary); --log defaults
to benchmark_log.csv in the current directory, and a missing log leaves the seed estimates.
No RAM check: every engine counts as fitting.
"""
import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core.i18n import Translator  # noqa: E402
from primeatlas.generation import engine_advisor, time_model  # noqa: E402
from primeatlas.generation.engine_advice_text import advice_text  # noqa: E402
from primeatlas.generation.run_output import format_duration_short  # noqa: E402


def _offset(text):
    value = engine_advisor.parse_offset(text)
    if value is None:
        raise argparse.ArgumentTypeError("the offset must be a number >= 1")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="Engine proposal for one run.")
    parser.add_argument("--floor", type=int, required=True)
    parser.add_argument("--windows", type=int, required=True, help="run width, windows of 10^7")
    parser.add_argument("--offset", type=_offset, default=engine_advisor.DEFAULT_BPSW_OFFSET)
    parser.add_argument("--write-files", action="store_true")
    parser.add_argument("--pt1-b", type=int, default=0)
    parser.add_argument("--log", default="benchmark_log.csv")
    args = parser.parse_args(argv)
    T = Translator("en")
    samples = time_model.read_samples(args.log)
    cals = engine_advisor.calibrations(samples, args.pt1_b)
    advice = engine_advisor.advise(samples, args.floor, args.windows, args.write_files,
                                   args.pt1_b, args.offset, cals=cals)
    text = advice_text(advice, T, format_duration_short, args.offset)
    for line in text:
        if line:
            print(line)
    if advice is not None:
        print("Options:")
        for o in advice.options:
            kind = "deterministic" if o.deterministic else "BPSW"
            seed = ", seed estimate" if o.estimated else ""
            print(f"  {o.engine:8} {format_duration_short(o.seconds):>8}  ({kind}{seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
