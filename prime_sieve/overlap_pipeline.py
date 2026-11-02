"""
overlap_pipeline.py -- a two-stage pipeline whose second stage runs in one helper thread.

run_overlapped() produces each item in the calling thread and consumes it in a helper
thread, so consume(k) runs while produce(k+1) does: prime_sieve_pt1.py sieves slab k+1
while slab k's windows are unpacked and written. The engine call and file I/O release the
GIL, so both stages make progress at once. Before handing over product k+1 the caller waits
for consume(k) to return, which caps the pipeline at two products alive (one being
consumed, one being produced): memory is two slab bitmaps whatever the run length.
Standard library only, so the engines stay runnable standalone under WSL.
"""
import concurrent.futures
import time
from collections import namedtuple

Timings = namedtuple("Timings", "produce_seconds consume_seconds wait_seconds")


def run_overlapped(items, produce, consume):
    """Calls produce(item) for each item in order in the calling thread and
    consume(item, product) in one helper thread, consume(k) overlapping produce(k+1).
    Consumes run in item order. Returns Timings: seconds spent in produce, in consume, and
    blocked waiting for a consume to return (the part of consuming not hidden behind
    producing).

    An exception from either stage stops the run and reaches the caller once the consume
    in flight has returned: a consume error after the produce in progress, a produce error
    after the pending consume (so an already produced item is still consumed)."""
    consume_seconds = [0.0]

    def _timed_consume(item, product):
        t0 = time.perf_counter()
        try:
            consume(item, product)
        finally:
            consume_seconds[0] += time.perf_counter() - t0

    produce_seconds = wait_seconds = 0.0
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = None
        try:
            for item in items:
                t0 = time.perf_counter()
                product = produce(item)
                t1 = time.perf_counter()
                produce_seconds += t1 - t0
                if pending is not None:
                    pending.result()
                    wait_seconds += time.perf_counter() - t1
                pending = pool.submit(_timed_consume, item, product)
                del product
            if pending is not None:
                t0 = time.perf_counter()
                pending.result()
                wait_seconds += time.perf_counter() - t0
        except BaseException:
            if pending is not None:
                concurrent.futures.wait([pending])
            raise
    return Timings(produce_seconds, consume_seconds[0], wait_seconds)
