"""Which time the Benchmark sieve chart measures (the Filter window's "Sieve measure").

phase: the engine's own sieve_seconds, its timer around the sieve alone (n/s, s/window).
wall: sieve_wall_seconds, timed by orchestrator_v3 from launching the scanner to its sieve-
done line -- Python start, imports, buffer allocation and library load included (n/s,
s/window).
overhead: the sieve speed the startup takes, phase n/s minus wall n/s, and that as % of the
phase n/s.
Native primesieve count is timed as one whole process, startup included: the same time is on
phase and wall, and it is not on overhead (no setup/sieve split to measure from outside).
A row without the time a measure needs has no point on it. The PARI/GP references are sieve
speeds, so they go with phase and wall only. No tkinter here.
"""
from collections import namedtuple

PHASE, WALL, OVERHEAD = "phase", "wall", "overhead"
MEASURES = (PHASE, WALL, OVERHEAD)
DEFAULT = PHASE

LABEL_KEYS = {PHASE: "bench.measure_phase", WALL: "bench.measure_wall",
              OVERHEAD: "bench.measure_overhead"}
TIP_KEY = "bench.measure_tip"
NOTE_KEY = "bench.measure_note"
HEADING_KEY = "bench.measure_heading"

ChartSpec = namedtuple("ChartSpec", "metric1 metric2 label_key1 label_key2 fmt1 fmt2 references")

_CHARTS = {
    PHASE: ChartSpec("sieve", "sieve_spw", "bench.axis_sieve_nps", "bench.axis_sieve_spw",
                     "{:,.0f}", "{:,.4f}", True),
    WALL: ChartSpec("sieve_wall", "sieve_wall_spw", "bench.axis_sieve_wall_nps",
                    "bench.axis_sieve_wall_spw", "{:,.0f}", "{:,.4f}", True),
    OVERHEAD: ChartSpec("sieve_overhead", "sieve_overhead_pct", "bench.axis_overhead_nps",
                        "bench.axis_overhead_pct", "{:,.0f}", "{:,.1f}", False),
}


def chart(measure):
    return _CHARTS[measure]


def note(measure, t):
    """The measure for the filter summary and the PDF subtitle; "" for the default."""
    return "" if measure == DEFAULT else t(NOTE_KEY, measure=t(LABEL_KEYS[measure]))


def heading(measure, t):
    """The measure named in the PDF's sieve page heading, whichever it is."""
    return t(HEADING_KEY, measure=t(LABEL_KEYS[measure]))
