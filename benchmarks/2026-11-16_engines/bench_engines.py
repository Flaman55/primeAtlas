"""
bench_engines.py -- one benchmark series of the engines v7.2 and v7.4 against each other and
against the Pseudosquares Prime Sieve, plus pt1 and pt1-pss on the deep floors, all on one
machine in one session.

Every run goes through the same code path the GUI uses: prime_sieve/orchestrator_v3.py for
the Atlas engines (PRIMEATLAS_SCANNER_VERSION selects v7.2, v7 = v7.4, pt1, pt1-pss) and
prime_sieve/pseudosquares_native.py for the Pseudosquares Prime Sieve (count mode). Each run
gets an empty scratch portal (CONSTELLATION_PORTAL_DIR), so the user's storage and its
benchmark_log.csv are never touched; the run's own benchmark_log.csv row is copied into OUT
and the scratch portal is deleted.

Protocol (the order is part of the method):
  1. Pseudosquares Prime Sieve, floors PSS_FLOORS, N = 10^9 numbers per floor (pass 1).
  2. For each N in SIZES and each floor: v7.2, v7.4, v7.4, v7.2 (ABBA), so that each engine
     takes an early and a late slot on every floor and slow drifts of the machine cancel.
  3. pt1 and pt1-pss on PT1_FLOORS, N = PT1_NUMBERS: pt1, pt1-pss, pt1-pss, pt1 (ABBA) where
     both engines reach the floor; pt1 alone twice above pt1-pss's last floor.
  4. Pseudosquares Prime Sieve again (pass 2).
Atlas runs write their windows (write_files = 1); pt1 runs without the verification P -> D
(PRIMEATLAS_PT1_VERIFY = 0), so its rows time the scan alone.

OUT is appended run by run and read back at start: an interrupted series resumes where it
stopped (a run counts as done when OUT holds its key). summarize() prints the mean and the
spread of each pair and every prime-count disagreement.

Usage (inside WSL, from anywhere):
    python3 bench_engines.py OUT.csv [--batches-per-worker B] [--workers W]
                                     [--only pss|ab|pt1] [--dry-run]
    python3 bench_engines.py OUT.csv --summary
Environment:
    BENCH_TMP          scratch folder (default ~/primeatlas_bench_engines, on the WSL file
                       system); must be empty or absent; each run uses a subfolder that is
                       deleted afterwards. A folder on a Windows drive (/mnt/...) makes the
                       write phase several times slower (2026-11-16 series: 15-24 s per 10^11
                       numbers, about 1.5 s in earlier GUI runs); the sieve times are not
                       affected.
    PSEUDOSQUARES_BIN  the Pseudosquares Prime Sieve binary, if not the installer's build
Requires psutil.
"""
import argparse
import csv
import datetime
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SIEVE_DIR = os.path.join(REPO, "prime_sieve")
ORCH = os.path.join(SIEVE_DIR, "orchestrator_v3.py")
PSS_RUNNER = os.path.join(SIEVE_DIR, "pseudosquares_native.py")
TMP = os.path.abspath(os.environ.get("BENCH_TMP")
                      or os.path.expanduser("~/primeatlas_bench_engines"))

WINDOW_M = 10 ** 7
AB_FLOORS = list(range(18, 31))
PSS_FLOORS = list(range(18, 31))
PSS_NUMBERS = 10 ** 9
SIZES = [10 ** 9, 10 ** 10, 10 ** 11]
PT1_FLOORS = list(range(30, 36))
PT1_PSS_LAST = 34          # pt1-pss refuses floors 35..37 (prime_sieve_pt1.py)
PT1_NUMBERS = 10 ** 9

PROTOCOL_FIELDS = ["seq", "key", "phase", "engine", "floor", "numbers", "slot", "utc_start",
                   "wall_seconds", "numbers_per_second", "peak_pss_mb", "returncode"]


class Monitor(threading.Thread):
    """Samples the process tree every 0.5 s: peak summed PSS (a buffer shared between
    workers counts once)."""

    def __init__(self, pid):
        super().__init__(daemon=True)
        self.pid, self.peak = pid, 0
        self.done = threading.Event()

    def run(self):
        while not self.done.is_set():
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
            self.peak = max(self.peak, total)
            self.done.wait(0.5)


def plan():
    """[(phase, engine, floor, numbers, slot), ...] in run order."""
    runs = [("pss1", "pss", f, PSS_NUMBERS, 1) for f in PSS_FLOORS]
    for n in SIZES:
        for f in AB_FLOORS:
            for slot, eng in enumerate(("v7.2", "v7", "v7", "v7.2"), 1):
                runs.append((f"ab_{n:.0e}", eng, f, n, slot))
    for f in PT1_FLOORS:
        order = ("pt1", "pt1-pss", "pt1-pss", "pt1") if f <= PT1_PSS_LAST else ("pt1", "pt1")
        for slot, eng in enumerate(order, 1):
            runs.append(("pt1", eng, f, PT1_NUMBERS, slot))
    runs += [("pss2", "pss", f, PSS_NUMBERS, 1) for f in PSS_FLOORS]
    return runs


def run_key(phase, engine, floor, numbers, slot):
    return f"{phase}|{engine}|{floor}|{numbers}|{slot}"


def done_keys(out):
    if not os.path.exists(out):
        return set()
    with open(out, newline="") as f:
        return {r["key"] for r in csv.DictReader(f) if r.get("returncode") == "0"}


def one_run(engine, floor, numbers, workers, batches):
    """Runs one engine on [10^floor, 10^floor + numbers) in a fresh scratch portal; returns
    (protocol fields, the run's benchmark_log.csv row)."""
    portal = os.path.join(TMP, "run")
    shutil.rmtree(portal, ignore_errors=True)
    os.makedirs(portal)
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal)
    windows = numbers // WINDOW_M
    if engine == "pss":
        cmd = [sys.executable, PSS_RUNNER, str(floor), "0", str(windows), str(WINDOW_M),
               "count", str(workers)]
    else:
        env["PRIMEATLAS_SCANNER_VERSION"] = engine
        env["PRIMEATLAS_PT1_VERIFY"] = "0"
        cmd = [sys.executable, ORCH, str(floor), str(windows), "0", "0", "1", "0",
               str(workers), str(batches), str(WINDOW_M)]
    utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.perf_counter()
    with open(os.path.join(TMP, "last_run.log"), "w") as log:
        proc = subprocess.Popen(cmd, env=env, cwd=SIEVE_DIR, stdout=log,
                                stderr=subprocess.STDOUT)
        mon = Monitor(proc.pid)
        mon.start()
        proc.wait()
    wall = time.perf_counter() - t0
    mon.done.set()
    mon.join()
    row = {}
    log_path = os.path.join(portal, "benchmark_log.csv")
    if os.path.exists(log_path):
        with open(log_path, newline="") as f:
            rows = list(csv.DictReader(f))
        row = rows[-1] if rows else {}
    shutil.rmtree(portal, ignore_errors=True)
    proto = {"utc_start": utc, "wall_seconds": f"{wall:.3f}",
             "numbers_per_second": f"{numbers / wall:.0f}",
             "peak_pss_mb": f"{mon.peak / 2 ** 20:.1f}", "returncode": str(proc.returncode)}
    return proto, row


def append(out, record):
    """Appends one record; the header is the union of the protocol fields and the
    benchmark_log.csv columns seen so far (the file is rewritten when a column is new)."""
    rows = []
    if os.path.exists(out):
        with open(out, newline="") as f:
            rows = list(csv.DictReader(f))
    rows.append(record)
    fields = list(PROTOCOL_FIELDS)
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    tmp = out + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, out)


def write_meta(out, args):
    """Records what was measured: commit, uncommitted changes, engine library hashes, tool
    versions, settings."""
    lines = [f"utc: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
             f"args: {vars(args)}"]
    for cmd in (["git", "-C", REPO, "log", "--oneline", "-1"],
                ["git", "-C", REPO, "status", "--short"],
                [sys.executable, os.path.join(SIEVE_DIR, "env_versions.py")],
                ["lscpu"], ["free", "-m"], ["uname", "-a"]):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            lines.append(f"$ {' '.join(cmd)}\n{res.stdout.strip()}")
        except (OSError, subprocess.TimeoutExpired) as e:
            lines.append(f"$ {' '.join(cmd)}\n[{e}]")
    for name in ("prime_sieve_engine_v7_2.so", "prime_sieve_engine_v7_4.so",
                 "prime_sieve_engine_pt1.so"):
        path = os.path.join(SIEVE_DIR, name)
        if os.path.exists(path):
            digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
            lines.append(f"sha256 {name} {digest}")
    with open(os.path.splitext(out)[0] + "_meta.txt", "a") as f:
        f.write("\n".join(lines) + "\n\n")


def summarize(out):
    """Mean and spread per (engine, floor, numbers), and every prime-count disagreement
    between runs of the same floor and size."""
    with open(out, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("returncode") == "0"]
    groups, primes = {}, {}
    for r in rows:
        k = (int(r["floor"]), int(r["numbers"]))
        groups.setdefault((r["engine"],) + k, []).append(float(r["numbers_per_second"]))
        if r.get("total_primes"):
            primes.setdefault(k, {}).setdefault(r["total_primes"], []).append(r["key"])
    print(f"{'engine':8s} {'floor':>5s} {'numbers':>8s} {'runs':>4s} {'M n/s mean':>11s} "
          f"{'spread %':>8s}")
    for (eng, floor, n), v in sorted(groups.items(), key=lambda x: (x[0][2], x[0][1], x[0][0])):
        mean = sum(v) / len(v)
        spread = (max(v) - min(v)) / mean * 100 if len(v) > 1 else 0.0
        print(f"{eng:8s} {floor:5d} {n:8.0e} {len(v):4d} {mean / 1e6:11.1f} {spread:8.1f}")
    bad = {k: v for k, v in primes.items() if len(v) > 1}
    print("prime counts: all runs agree" if not bad else "PRIME COUNT DISAGREEMENT:")
    for k, v in sorted(bad.items()):
        print(f"  floor {k[0]}, {k[1]:.0e} numbers: {v}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--batches-per-worker", type=int, default=1)
    ap.add_argument("--only", choices=("pss", "ab", "pt1"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    if args.summary:
        summarize(out)
        return
    runs = plan()
    if args.only:
        runs = [r for r in runs if r[0].startswith(args.only)]
    done = done_keys(out)
    todo = [r for r in runs if run_key(*r) not in done]
    print(f"{len(runs)} runs in the plan, {len(runs) - len(todo)} already in {out}, "
          f"{len(todo)} to go", flush=True)
    if args.dry_run:
        for r in todo:
            print("  ", run_key(*r))
        return
    if os.path.isdir(TMP) and os.listdir(TMP):
        sys.exit(f"BENCH_TMP {TMP} is not empty; empty it or point BENCH_TMP elsewhere")
    os.makedirs(TMP, exist_ok=True)
    write_meta(out, args)
    seq = len(done)
    for phase, engine, floor, numbers, slot in todo:
        seq += 1
        key = run_key(phase, engine, floor, numbers, slot)
        print(f"[{time.strftime('%H:%M:%S')}] {seq} {key}", flush=True)
        proto, row = one_run(engine, floor, numbers, args.workers, args.batches_per_worker)
        record = {"seq": seq, "key": key, "phase": phase, "engine": engine, "floor": floor,
                  "numbers": numbers, "slot": slot, **proto}
        for k, v in row.items():
            record.setdefault(k, v)
        append(out, record)
        print(f"    {float(proto['numbers_per_second']) / 1e6:,.1f} M n/s, "
              f"{proto['wall_seconds']} s, primes {row.get('total_primes', '?')}, "
              f"rc {proto['returncode']}", flush=True)
    summarize(out)
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    main()
