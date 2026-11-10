"""pt1 runs with a verification as two chart lines: the sieve alone (P) and the sieve with the
proof (D proof).

A pt1 run with PRIMEATLAS_PT1_VERIFY=1 logs its proof time in proof_seconds, part of
total_seconds and of the loop time, not of sieve_seconds (benchmark_log_schema.py). The charts
draw such a row twice (chart_rows()): as a "P" run without the proof (total and loop times
less proof_seconds, the speeds recomputed) and as a KIND_PROOF run with it (proof_seconds
added to sieve_seconds as well), so the legend shows both lines and either can be hidden.
The table keeps the one logged row. Each copy names its logged row under SOURCE_KEY
(source()), so selecting that row in the table selects both points. No tkinter here.
"""
import storage_kinds

KIND_PROOF = "D proof"
SOURCE_KEY = "_source_row"


def proof_seconds(row):
    """The row's proof time in seconds, None when it has none (or not a positive one)."""
    try:
        value = float(row.get("proof_seconds") or "")
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def source(row):
    """The logged row a chart row comes from (the row itself unless chart_rows() copied it)."""
    return row.get(SOURCE_KEY, row)


def _scaled(row, seconds_field, rate_fields, minus):
    """Subtracts `minus` from row[seconds_field] and rescales each per-second field of
    rate_fields to the shorter time; fields that are blank or unreadable stay as they are."""
    try:
        seconds = float(row.get(seconds_field) or "")
    except (TypeError, ValueError):
        return
    shorter = seconds - minus
    if shorter <= 0:
        return
    row[seconds_field] = f"{shorter:.3f}"
    for field in rate_fields:
        try:
            row[field] = f"{float(row.get(field) or '') * seconds / shorter:.2f}"
        except (TypeError, ValueError):
            pass


def _per_window(row, seconds_field, field):
    try:
        row[field] = f"{float(row[seconds_field]) / int(row['windows_written']):.6f}"
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass


def split(row):
    """[P copy, KIND_PROOF copy] of a row with proof_seconds, else [row]."""
    proof = proof_seconds(row)
    if proof is None or SOURCE_KEY in row:
        return [row]
    sieve_only = dict(row, kind=storage_kinds.KIND_P)
    sieve_only[SOURCE_KEY] = row
    _scaled(sieve_only, "total_seconds", ("primes_per_second",), proof)
    _scaled(sieve_only, "loop_session_seconds", ("loop_numbers_per_second",), proof)
    _per_window(sieve_only, "total_seconds", "seconds_per_window")
    _per_window(sieve_only, "loop_session_seconds", "loop_seconds_per_window")
    with_proof = dict(row, kind=KIND_PROOF)
    with_proof[SOURCE_KEY] = row
    try:
        with_proof["sieve_seconds"] = f"{float(row.get('sieve_seconds') or '') + proof:.3f}"
    except (TypeError, ValueError):
        pass
    return [sieve_only, with_proof]


def chart_rows(rows):
    """The rows as the charts draw them: every row with a proof split in two (split())."""
    return [out for row in rows for out in split(row)]
