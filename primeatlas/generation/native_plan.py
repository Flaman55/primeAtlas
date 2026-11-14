"""
native_plan.py -- the range of a Quick-gen native run (Pseudosquares, primesieve with Native
on) from its fields: From (a number; blank = the Floor's start), Width (windows of `window_m`
numbers) and Pseudosquares' Threads.

A native run writes nothing into the storage, so the plan never looks at it: From picks its
floor (digit count) and the window holding it, rounded down to the window grid; the range
never leaves that floor and never passes the program's stop (Pseudosquares: MAX_STOP,
~1.73 * 10^33, in floor 33; primesieve: 2^64 - 1, in floor 19; the runners clamp the same
way). No tkinter here.
"""
import pseudosquares_const as const

from ..core.storage import digit_count_floor

AUTO_THREADS = 0  # the program picks its thread count


def parse_threads(text):
    """Threads field: blank / "Auto" / 0 -> AUTO_THREADS, a positive integer as given,
    None for anything else."""
    text = (text or "").strip()
    if not text or text.lower() == "auto":
        return AUTO_THREADS
    if not text.isdigit():
        return None
    return int(text)


def plan(start, floor, width_mult, window_m, max_stop=const.MAX_STOP):
    """{floor, target_idx_start, count, lo, hi, clamped} of one run up to the program's
    inclusive stop `max_stop`, or {"error": key}: from_required (no From and no Floor),
    range_negative (From below 1), beyond_ceiling (past max_stop), width_invalid (Width
    below 1)."""
    if not isinstance(width_mult, int) or width_mult < 1:
        return {"error": "width_invalid"}
    if start is None:
        if floor is None or floor < 0:
            return {"error": "from_required"}
        start = 10 ** floor
    if start < 1:
        return {"error": "range_negative"}
    if start > max_stop:
        return {"error": "beyond_ceiling"}
    floor = digit_count_floor(start)
    idx = (start - 10 ** floor) // window_m
    lo = 10 ** floor + idx * window_m
    hi = min(lo + width_mult * window_m, 10 ** (floor + 1), max_stop + 1)
    count = -(-(hi - lo) // window_m)
    return {"floor": floor, "target_idx_start": idx, "count": count, "lo": lo, "hi": hi,
            "clamped": hi - lo < width_mult * window_m}
