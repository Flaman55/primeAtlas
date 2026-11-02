"""
test_overlap_pipeline.py -- prime_sieve/overlap_pipeline.py runs consume(k) in one helper
thread while produce(k+1) runs in the caller, and prime_sieve_pt1.py writes its slabs
through it.

A. Every item is produced and consumed once, consumed in item order with its own product.
B. consume(k) overlaps produce(k+1): consume(0) waits for a signal that only produce(1) sends.
C. Bounded: produce(k+2) starts only after consume(k) returns (at most two products alive).
D. A consume error stops the run: no produce starts after the one in progress, the error
   reaches the caller.
E. A produce error waits for the pending consume to finish, then reaches the caller.
F. No items: no calls, zero timings. Timings: produce/consume seconds cover the calls.
G. prime_sieve_pt1.py hands its slabs to run_overlapped().

Usage:
    python unitTests/test_overlap_pipeline.py
"""
import os
import re
import sys
import threading
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_order(pipe):
    print("\n--- A. order ---")
    produced, consumed = [], []

    def produce(item):
        produced.append(item)
        return item * 10

    pipe.run_overlapped([1, 2, 3, 4], produce, lambda item, p: consumed.append((item, p)))
    check(produced == [1, 2, 3, 4], "each item produced once, in order")
    check(consumed == [(1, 10), (2, 20), (3, 30), (4, 40)],
          "each item consumed once, in order, with its own product")
    check(threading.active_count() == 1, "no helper thread left running")


def _test_overlap(pipe):
    print("\n--- B. consume(k) overlaps produce(k+1) ---")
    signal = threading.Event()
    seen = {}

    def produce(item):
        if item == 1:
            signal.set()
        return item

    def consume(item, _product):
        if item == 0:
            seen["signalled"] = signal.wait(5)

    pipe.run_overlapped([0, 1], produce, consume)
    check(seen.get("signalled") is True, "consume(0) sees produce(1) run meanwhile")


def _test_bounded(pipe):
    print("\n--- C. at most two products alive ---")
    lock = threading.Lock()
    consumed_done = []
    violations = []

    def produce(item):
        with lock:
            if item >= 2 and (item - 2) not in consumed_done:
                violations.append(item)
        return item

    def consume(item, _product):
        time.sleep(0.02)
        with lock:
            consumed_done.append(item)

    pipe.run_overlapped(list(range(6)), produce, consume)
    check(not violations, f"produce(k+2) waits for consume(k) (violations: {violations})")


def _test_consume_error(pipe):
    print("\n--- D. a consume error stops the run ---")
    produced = []

    def produce(item):
        produced.append(item)
        return item

    def consume(item, _product):
        if item == 1:
            raise OSError("disk full")

    try:
        pipe.run_overlapped(list(range(6)), produce, consume)
        raised = None
    except OSError as exc:
        raised = exc
    check(raised is not None and str(raised) == "disk full", "the consume error reaches the caller")
    check(produced == [0, 1, 2], f"no produce after the one in progress ({produced})")
    check(threading.active_count() == 1, "no helper thread left running")


def _test_produce_error(pipe):
    print("\n--- E. a produce error waits for the pending consume ---")
    consumed = []

    def produce(item):
        if item == 1:
            raise RuntimeError("pt1 engine error")
        return item

    def consume(item, _product):
        time.sleep(0.1)
        consumed.append(item)

    try:
        pipe.run_overlapped([0, 1, 2], produce, consume)
        raised = None
    except RuntimeError as exc:
        raised = exc
    check(raised is not None and str(raised) == "pt1 engine error",
          "the produce error reaches the caller")
    check(consumed == [0], f"the pending consume finished first ({consumed})")


def _test_empty_and_timings(pipe):
    print("\n--- F. no items; timings ---")
    calls = []
    t = pipe.run_overlapped([], calls.append, lambda i, p: calls.append(i))
    check(not calls and t.produce_seconds == 0 and t.consume_seconds == 0 and t.wait_seconds == 0,
          "no items: no calls, zero timings")

    t = pipe.run_overlapped([0, 1], lambda i: time.sleep(0.05), lambda i, p: time.sleep(0.1))
    check(t.produce_seconds >= 0.09, f"produce_seconds covers both produces ({t.produce_seconds:.3f})")
    check(t.consume_seconds >= 0.19, f"consume_seconds covers both consumes ({t.consume_seconds:.3f})")
    check(t.wait_seconds >= 0.09, f"wait_seconds counts the caller blocked on consume "
                                  f"({t.wait_seconds:.3f})")


def _test_pt1_uses_it():
    print("\n--- G. prime_sieve_pt1.py writes through run_overlapped() ---")
    with open(os.path.join(_REPO_ROOT, "prime_sieve", "prime_sieve_pt1.py"), encoding="utf-8") as f:
        source = f.read()
    check(re.search(r"\brun_overlapped\(", source) is not None,
          "prime_sieve_pt1.py calls run_overlapped()")


def main():
    try:
        import overlap_pipeline as pipe
    except ImportError as exc:
        check(False, f"prime_sieve/overlap_pipeline.py imports ({exc})")
    else:
        _test_order(pipe)
        _test_overlap(pipe)
        _test_bounded(pipe)
        _test_consume_error(pipe)
        _test_produce_error(pipe)
        _test_empty_and_timings(pipe)
    _test_pt1_uses_it()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
