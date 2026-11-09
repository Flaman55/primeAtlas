"""Names and chart membership of benchmark_log.csv rows on the Benchmark charts.

A line is what one engine build measured on one thread setup: its name is the engine (or
its version when that names the engine, "v6.0"), the store kind of P runs, the sieve
threads ("24 thr", "2x24 thr" for two instances side by side, "GPU") and the write threads
("write 8", "write ?" for a writing row from before that column); rows from before the
thread columns keep the bare engine name. width_label() names a point's range ("@ 10^11"):
on the floor axis a chart can set points of different widths side by side. Names are ASCII:
the PDF font has no other characters. primesieve rows say how they were measured: the
wrapper converts the library's result into Atlas windows ("primesieve (Atlas format)"), the
native program counts ("primesieve count (native)") or prints ("primesieve print (native)");
the Pseudosquares Prime Sieve program has the same two native modes ("Pseudosquares count
(native)", "Pseudosquares print (native)"). A native count sieves the range and counts the
primes -- an engine's sieve phase -- so it is on the sieve charts only; a native print sieves and outputs every prime with no split
between the two -- a whole run -- so it is on the whole-run chart only (CHART_METRICS). Both
log the program's peak RAM and write no Atlas windows: they are on RAM per run, not per window. A
native count is one process timed from outside, startup included (WHOLE_PROCESS_SIEVE): its
one time is both its sieve phase and its sieve with startup, and it has no startup/sieve
split, so it is not on the startup-overhead measure.
No tkinter here.
"""
import benchmark_log_schema as schema
import storage_kinds

ENGINE_LABELS = {
    schema.ENGINE_PRIMESIEVE_ATLAS: "primesieve (Atlas format)",
    schema.ENGINE_PRIMESIEVE_PRINT: "primesieve print (native)",
    schema.ENGINE_PRIMESIEVE_COUNT: "primesieve count (native)",
    schema.ENGINE_PSEUDOSQUARES_PRINT: "Pseudosquares print (native)",
    schema.ENGINE_PSEUDOSQUARES_COUNT: "Pseudosquares count (native)",
}

# Native programs counting a range: one process, no Atlas windows, nothing written.
NATIVE_COUNT_ENGINES = frozenset({schema.ENGINE_PRIMESIEVE_COUNT,
                                  schema.ENGINE_PSEUDOSQUARES_COUNT})
NATIVE_PRINT_ENGINES = frozenset({schema.ENGINE_PRIMESIEVE_PRINT,
                                  schema.ENGINE_PSEUDOSQUARES_PRINT})

# Engines that write no Atlas windows: their seconds per window count 10^7-number windows.
NO_WINDOW_ENGINES = NATIVE_COUNT_ENGINES

# Engines whose sieve_seconds is one whole process timed from outside, startup included.
WHOLE_PROCESS_SIEVE = NATIVE_COUNT_ENGINES

# Metrics a row's engine is drawn on; engines not listed are on every chart.
CHART_METRICS = {
    **{engine: frozenset({"sieve", "sieve_spw", "sieve_wall", "sieve_wall_spw", "ram"})
       for engine in NATIVE_COUNT_ENGINES},
    **{engine: frozenset({"growth", "ram"}) for engine in NATIVE_PRINT_ENGINES},
}


def row_engine(row):
    return row.get("engine") or ("hybrid" if row.get("instance_of_n") == "hybrid" else "unknown")


def on_chart(row, metric):
    allowed = CHART_METRICS.get(row_engine(row))
    return allowed is None or metric in allowed


def _instances(row):
    try:
        return int(str(row.get("instance_of_n") or "").split("/")[1])
    except (IndexError, ValueError):
        return 1


def sieve_threads_label(row):
    """"24 thr", "2x24 thr" (two instances side by side), "GPU", or "" without a count."""
    threads = str(row.get("threads") or "").strip()
    if not threads or threads == schema.THREADS_GPU:
        return threads
    instances = _instances(row)
    return f"{instances}x{threads} thr" if instances > 1 else f"{threads} thr"


def write_threads_label(row):
    """"8", "?" for a writing row from before the column, "" for a run that writes nothing
    or a row without thread columns."""
    write = str(row.get("write_threads") or "").strip()
    if not write and sieve_threads_label(row) and row_engine(row) not in NATIVE_COUNT_ENGINES:
        write = "?"
    return write


def threads_label(row):
    """"24 thr", "2x24 thr", "GPU", plus ", write 8" when the row names its write
    threads; "" when the row has no thread count."""
    label = sieve_threads_label(row)
    if not label:
        return ""
    write = write_threads_label(row)
    return f"{label}, write {write}" if write else label


def width_label(numbers):
    """"10^11", "2x10^11", "1.5x10^10" for a range of `numbers` integers; "" if unknown."""
    try:
        numbers = int(numbers)
    except (TypeError, ValueError):
        return ""
    if numbers <= 0:
        return ""
    exponent = len(str(numbers)) - 1
    mantissa = numbers / 10 ** exponent
    if mantissa == 1:
        return f"10^{exponent}"
    return f"{mantissa:.3g}x10^{exponent}"


def base_name(row):
    """The line name without threads: engine or its version, primesieve path, P kind."""
    engine = row_engine(row)
    version = (row.get("engine_version") or "").strip()
    label = ENGINE_LABELS.get(engine, engine)
    if version and version.startswith(engine) and engine not in ENGINE_LABELS:
        name = version
    else:
        name = f"{label} {version}" if version else label
    kind = row.get("kind") or storage_kinds.KIND_D
    return name if kind == storage_kinds.KIND_D else f"{name} {kind}"


def line_name(row):
    threads = threads_label(row)
    name = base_name(row)
    return f"{name}, {threads}" if threads else name
