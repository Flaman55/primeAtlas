"""
bench_atlas.py -- times the PrimeAtlas sieve pipeline (prime_sieve/orchestrator_v3.py, the
engine the GUI launches) against the primesieve command-line tool on the same ranges.

Runs inside WSL. For every floor 10^N it sieves `windows x window_m` consecutive numbers
starting at 10^N, once per mode:
  count -- write_files=0 (primesieve: --count)
  write -- write_files=1 (primesieve: --print redirected to a file; measured on the lowest
           floor only, since primesieve --print is single-threaded by design)
primesieve is skipped above 2^64, where it rejects the input.

Each run reports wall time, the pipeline's own sieve/write split (read back from the
benchmark_log.csv row it writes), peak summed PSS of the whole process tree (a buffer shared
between workers counts once) and the size of the files it produced. Output goes to an empty
scratch portal (CONSTELLATION_PORTAL_DIR), which is deleted after each run, so the user's
storage and its benchmark_log.csv are never touched.

Usage:
    python3 bench_atlas.py OUT.json FLOORS [WINDOWS [WINDOW_M [MODES [PRIMESIEVE [WORKERS]]]]]
    e.g. python3 bench_atlas.py a.json 10,19,22,25 1000 10000000 count,write 1 24

Environment:
    PRIMESIEVE_BIN   primesieve executable (default: primesieve on PATH)
    BENCH_TMP        scratch portal folder; must not exist yet (default: ./bench_tmp)
Requires psutil.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import psutil

ORCH = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                    "prime_sieve", "orchestrator_v3.py"))
PRIMESIEVE = os.environ.get("PRIMESIEVE_BIN") or shutil.which("primesieve") or "primesieve"
TMP = os.path.abspath(os.environ.get("BENCH_TMP", "bench_tmp"))
OUT = sys.argv[1]
FLOORS = [int(x) for x in sys.argv[2].split(",")]
WINDOWS = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
WINDOW_M = int(sys.argv[4]) if len(sys.argv) > 4 else 10 ** 7
MODES = sys.argv[5].split(",") if len(sys.argv) > 5 else ["count", "write"]
WITH_PRIMESIEVE = (sys.argv[6] == "1") if len(sys.argv) > 6 else True
WORKERS = int(sys.argv[7]) if len(sys.argv) > 7 else 24
DIST = WINDOWS * WINDOW_M
U64 = 2 ** 64


class Monitor(threading.Thread):
    """Samples the process tree every 0.5 s: peak summed PSS and peak process count."""

    def __init__(self, pid):
        super().__init__(daemon=True)
        self.pid, self.stop, self.peak_pss, self.peak_procs = pid, False, 0, 0

    def run(self):
        while not self.stop:
            try:
                root = psutil.Process(self.pid)
                procs = [root] + root.children(recursive=True)
            except psutil.NoSuchProcess:
                break
            total = 0
            for p in procs:
                try:
                    total += p.memory_full_info().pss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            self.peak_pss = max(self.peak_pss, total)
            self.peak_procs = max(self.peak_procs, len(procs))
            time.sleep(0.5)


def timed(cmd, env=None, stdout=None):
    """Runs cmd to completion. Wall time includes up to 0.5 s of monitor join; short
    primesieve runs should be read from its own reported 'Seconds:' line instead."""
    t0 = time.time()
    proc = subprocess.Popen(cmd, env=env, stdout=stdout or subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    mon = Monitor(proc.pid)
    mon.start()
    out = proc.communicate()[0] if stdout is None else ""
    proc.wait()
    mon.stop = True
    mon.join()
    return {"seconds": time.time() - t0, "returncode": proc.returncode,
            "peak_pss_mb": mon.peak_pss / 2 ** 20, "peak_procs": mon.peak_procs,
            "tail": (out or "")[-1500:]}


def dir_size(path):
    total, files = 0, 0
    for root, _d, names in os.walk(path):
        for n in names:
            if n.startswith("PRIME_WINDOW_"):
                total += os.path.getsize(os.path.join(root, n))
                files += 1
    return total, files


def atlas(floor, write):
    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=TMP)
    # orchestrator_v3 CLI: floor, window count, auto-start 0, start window 0, write_files,
    # sieving-prime count 0, workers, batches per worker, window width.
    cmd = [sys.executable, ORCH, str(floor), str(WINDOWS), "0", "0", "1" if write else "0",
           "0", str(WORKERS), "2", str(WINDOW_M)]
    r = timed(cmd, env=env)
    log = os.path.join(TMP, "benchmark_log.csv")
    if os.path.exists(log):
        rows = list(csv.DictReader(open(log)))
        if rows:
            row = rows[-1]
            for k in ("total_seconds", "base_gen_seconds", "sieve_seconds", "write_seconds",
                      "total_primes", "bytes_written", "max_child_rss_mb"):
                r[k] = row.get(k)
    r["output_bytes"], r["output_files"] = dir_size(TMP)
    shutil.rmtree(TMP, ignore_errors=True)
    return r


def primesieve(floor, write):
    start = 10 ** floor
    if start + DIST > U64:
        return {"skipped": "beyond 2^64"}
    cmd = [PRIMESIEVE, str(start), f"--dist={DIST}", f"--threads={WORKERS}"]
    if not write:
        return timed(cmd + ["--count"])
    os.makedirs(TMP, exist_ok=True)
    path = os.path.join(TMP, "primesieve_print.txt")
    with open(path, "w") as f:
        r = timed(cmd + ["--print"], stdout=f)
    r["output_bytes"] = os.path.getsize(path)
    shutil.rmtree(TMP, ignore_errors=True)
    return r


def main():
    if os.path.exists(TMP):
        sys.exit(f"BENCH_TMP {TMP} already exists; point it at a new folder")
    results = {"floors": FLOORS, "dist": DIST, "windows": WINDOWS, "window_m": WINDOW_M,
               "workers": WORKERS, "runs": []}
    plan = [(f, m == "write") for m in MODES for f in FLOORS]
    for floor, write in plan:
        mode = "write" if write else "count"
        print(f"[{time.strftime('%H:%M:%S')}] floor {floor} {mode}", flush=True)
        ps = (primesieve(floor, write) if WITH_PRIMESIEVE and (not write or floor == min(FLOORS))
              else {"skipped": "not in this series"})
        at = atlas(floor, write)
        results["runs"].append({"floor": floor, "mode": mode, "primesieve": ps, "atlas": at})
        print(json.dumps({"floor": floor, "mode": mode, "ps_s": ps.get("seconds"),
                          "atlas_s": at.get("seconds"), "sieve_s": at.get("sieve_seconds"),
                          "write_s": at.get("write_seconds"),
                          "pss_mb": round(at["peak_pss_mb"]), "primes": at.get("total_primes"),
                          "rc": at["returncode"], "bytes": at.get("output_bytes")}), flush=True)
        with open(OUT, "w") as f:
            json.dump(results, f, indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
