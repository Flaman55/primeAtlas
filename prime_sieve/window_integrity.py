"""Completeness check for PGS2 window files (format: prime_sieve_v1.py, pgs2_vector.py).

Scanners write a window with one plain open(path, "wb"), so a process killed during the
write leaves a truncated file. A complete file holds its header plus exactly count - 1
LEB128 gaps: the payload has count - 1 bytes with the high bit clear (one per varint) and
its last byte is one of them. repair_recent() runs the full check only on windows written
shortly before a reference time, since only a write in flight at the kill can be cut.

No tkinter and no primeatlas imports: used by orchestrator_v3.py inside WSL and by the GUI.
"""
import os
from concurrent.futures import ThreadPoolExecutor

PGS_MAGIC = b"PGS2"
_HEADER_MAX = 4 + 1 + 255 + 4 + 4


def _parse_header(data):
    """(count, generated_at, payload_offset) of a PGS2 header, or None if it is cut or
    not PGS2."""
    if len(data) < 5 or data[:4] != PGS_MAGIC:
        return None
    pos = 5 + data[4]
    if len(data) < pos + 8:
        return None
    count = int.from_bytes(data[pos:pos + 4], "big")
    generated_at = int.from_bytes(data[pos + 4:pos + 8], "big")
    return count, generated_at, pos + 8


def read_window_header(path):
    """(count, generated_at) from a window's header; ValueError when the header is cut or
    not PGS2. Unbuffered, same reason as pgs2_vector.read_window_count()."""
    with open(path, "rb", buffering=0) as f:
        parsed = _parse_header(f.read(_HEADER_MAX))
    if parsed is None:
        raise ValueError(f"{path}: no complete PGS2 header")
    return parsed[0], parsed[1]


def is_complete(path):
    """True when `path` is a whole PGS2 window: a parseable header and a payload of exactly
    count - 1 varints. False for a missing, cut or foreign file."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return False
    parsed = _parse_header(data)
    if parsed is None:
        return False
    count, _generated_at, start = parsed
    payload = data[start:]
    if count <= 1:
        return len(payload) == 0
    if not payload or payload[-1] & 0x80:
        return False
    terminators = len(payload) - sum(1 for b in payload if b & 0x80)
    return terminators == count - 1


def repair_recent(paths, reference_time=None, window_seconds=60, workers=8):
    """Deletes the incomplete windows among `paths` that may have been cut by a kill and
    returns their paths in input order. A path whose header does not parse is cut. A path
    with a parseable header is fully checked when its generated_at is at most
    `window_seconds` older than `reference_time` (default: the newest generated_at among
    the readable headers); older windows were finished long before the kill."""
    def _header(path):
        try:
            return read_window_header(path)
        except FileNotFoundError:
            return "missing"
        except (OSError, ValueError):
            return None

    paths = list(paths)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        headers = list(pool.map(_header, paths))
    stamps = [h[1] for h in headers if isinstance(h, tuple)]
    if reference_time is None:
        reference_time = max(stamps) if stamps else 0
    deleted = []
    for path, header in zip(paths, headers):
        if header == "missing":
            continue
        cut = header is None or (header[1] >= reference_time - window_seconds
                                 and not is_complete(path))
        if cut:
            try:
                os.remove(path)
                deleted.append(path)
            except OSError:
                pass
    return deleted
