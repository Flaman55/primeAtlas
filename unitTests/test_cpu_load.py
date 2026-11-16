"""
test_cpu_load.py -- the GUI side of a run's machine and CPU load columns: the Windows CPU
counters (core/cpu_load.py), this computer's id (core/windows_hardware.machine_id), the launch
environment (wsl_command) and the load file a WSL run's runner keeps (logged_runners).

A. CpuSampler with a fake clock and counter reader: no samples or one sample -> None; the
   busy share over the last N seconds compares the newest sample with the newest one at or
   before N seconds back (the oldest when the history is shorter); a reader returning None
   adds nothing; samples older than the kept history are dropped; a counter going back -> None.
B. read_system_counters(): on Windows an (idle, total) pair with 0 <= idle <= total that
   grows between two reads; elsewhere None.
C. machine_id(guid): 12 lowercase hex digits, the same for the same GUID whatever its case or
   spaces, different for another GUID, None for no GUID; the computer's own id has the
   same form (or None off Windows) and does not contain the GUID itself.
D. build_wsl_logged_command(): names the run's load file (the log path with .load, in its WSL
   form), the machine id and the before value when known, and leaves out what is unknown;
   run_load_path() swaps only the extension.
E. WslLoggedRunner keeps the load file: written before the process starts (so the engine's
   import reads a start pair), updated while it runs, removed with the log at the end; a
   process importing run_load gets a during value in 0..100; with a reader returning None no
   file is written and the run still finishes.
F. The real app starts the app-wide sampler when it is built, so a launch soon after has a
   before value (on Windows, two samples a second apart).

Usage:
    python unitTests/test_cpu_load.py
"""
import json
import os
import queue
import re
import sys
import tempfile
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core import cpu_load, windows_hardware  # noqa: E402
from primeatlas.generation import logged_runners, wsl_command  # noqa: E402
import run_load  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


class _Fake:
    def __init__(self):
        self.now = 0.0
        self.counters = (0, 0)

    def clock(self):
        return self.now

    def reader(self):
        return self.counters


def _test_sampler():
    print("\n--- A. CpuSampler ---")
    fake = _Fake()
    sampler = cpu_load.CpuSampler(reader=fake.reader, clock=fake.clock, keep_seconds=30)
    check(sampler.busy_over_last(5) is None, "no samples -> None")
    sampler.sample()
    check(sampler.busy_over_last(5) is None, "one sample -> None")
    # Each second: 100 ticks, of them idle 100 (s 1-3), then 0 (s 4-10).
    for second in range(1, 11):
        fake.now = float(second)
        idle, total = fake.counters
        fake.counters = (idle + (100 if second <= 3 else 0), total + 100)
        sampler.sample()
    check(sampler.busy_over_last(5) == 100.0, "last 5 s fully busy -> 100")
    check(sampler.busy_over_last(10) == 70.0, "last 10 s: 3 idle of 10 -> 70")
    check(sampler.busy_over_last(60) == 70.0, "history shorter than asked -> from the oldest")
    check(sampler.busy_over_last(7.5) == 87.5,
          "7.5 s back -> the newest sample at or before t=2.5 (t=2) -> 87.5")
    fake.now = 11.0
    none_reader = cpu_load.CpuSampler(reader=lambda: None, clock=fake.clock)
    none_reader.sample()
    none_reader.sample()
    check(none_reader.busy_over_last(5) is None, "a reader with no counters adds nothing")
    for second in range(11, 51):
        fake.now = float(second)
        sampler.sample()
    check(len(sampler.samples()) <= 32, f"old samples dropped ({len(sampler.samples())} kept)")
    back = cpu_load.CpuSampler(reader=fake.reader, clock=fake.clock)
    fake.counters = (500, 5000)
    back.sample()
    fake.now += 1
    fake.counters = (400, 4000)
    back.sample()
    check(back.busy_over_last(5) is None, "counters going back -> None")


def _test_system_counters():
    print("\n--- B. read_system_counters ---")
    first = cpu_load.read_system_counters()
    if os.name != "nt":
        check(first is None, "off Windows -> None")
        return
    time.sleep(0.3)
    second = cpu_load.read_system_counters()
    check(isinstance(first, tuple) and len(first) == 2 and 0 <= first[0] <= first[1],
          f"an (idle, total) pair ({first})")
    check(second is not None and second[1] > first[1] and second[0] >= first[0],
          f"the total grows between reads ({first} -> {second})")
    pct = run_load.busy_pct(first, second)
    check(pct is not None and 0 <= pct <= 100, f"busy share of the step in 0..100 ({pct})")


def _test_machine_id():
    print("\n--- C. machine_id ---")
    guid = "6F1C2A3B-1111-2222-3333-444455556666"
    one = windows_hardware.machine_id(guid)
    check(bool(re.fullmatch(r"[0-9a-f]{12}", one or "")), f"12 hex digits ({one})")
    check(windows_hardware.machine_id(f"  {guid.lower()} ") == one, "case and spaces ignored")
    check(windows_hardware.machine_id(guid.replace("6666", "6667")) != one,
          "another GUID -> another id")
    check(windows_hardware.machine_id("") is None and windows_hardware.machine_id(None) is None,
          "no GUID -> None")
    own = windows_hardware.this_machine_id()
    if os.name == "nt":
        check(bool(re.fullmatch(r"[0-9a-f]{12}", own or "")), f"this computer's id ({own})")
        check(windows_hardware.this_machine_id() == own, "the same on a second read")
    else:
        check(own is None, "off Windows -> None")


def _test_launch_env():
    print("\n--- D. the launch environment ---")
    check(wsl_command.run_load_path("C:\\p\\.generation_logs\\loop_1_2.log")
          == "C:\\p\\.generation_logs\\loop_1_2.load", "run_load_path swaps .log for .load")
    cmd = wsl_command.build_wsl_logged_command(
        ["python3", "x.py"], "D:\\store\\.generation_logs\\v_1.log", "D:\\store\\e.exit",
        "D:\\store", run_context=("3f9a0c1d2e4b", 12.34))
    bash = cmd[-1]
    check(f"{run_load.LOAD_FILE_ENV}=/mnt/d/store/.generation_logs/v_1.load " in bash,
          "names the load file in its WSL form")
    check(f"{run_load.MACHINE_ID_ENV}=3f9a0c1d2e4b " in bash, "names the machine id")
    check(f"{run_load.CPU_BUSY_BEFORE_ENV}=12.3 " in bash, "names the before value, one decimal")
    check(bash.index(run_load.LOAD_FILE_ENV) < bash.index("python3"), "all before the argv")
    unknown = wsl_command.build_wsl_logged_command(
        ["python3", "x.py"], "D:\\s\\a.log", "D:\\s\\e", "D:\\s", run_context=(None, None))[-1]
    check(run_load.MACHINE_ID_ENV not in unknown and run_load.CPU_BUSY_BEFORE_ENV not in unknown
          and run_load.LOAD_FILE_ENV in unknown,
          "unknown id and before left out, the load file still named")
    default = wsl_command.build_wsl_logged_command(["python3"], "D:\\s\\a.log", "D:\\s\\e", "D:\\s")
    own = windows_hardware.this_machine_id()
    check((own is None) or f"{run_load.MACHINE_ID_ENV}={own} " in default[-1],
          "by default the computer's own id is named")


_CHILD = """
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
import run_load
end = time.time() + 2.5
while time.time() < end:
    pass
print("FIELDS " + json.dumps(run_load.row_fields(os.environ)), flush=True)
"""


def _run(runner):
    runner.start()
    lines, code = "", "missing"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            item = runner.output_queue.get(timeout=1)
        except queue.Empty:
            continue
        if isinstance(item, tuple):
            code = item[1]
            break
        lines += item
    return lines, code


def _test_runner(folder):
    print("\n--- E. the runner keeps the load file ---")
    log_path = os.path.join(folder, "r_1.log")
    exit_path = os.path.join(folder, "r_1.exit")
    load_path = wsl_command.run_load_path(log_path)
    env_before = os.environ.get(run_load.LOAD_FILE_ENV)
    os.environ[run_load.LOAD_FILE_ENV] = load_path
    seen = []
    try:
        script = (f"import subprocess, sys; "
                  f"r = subprocess.run([sys.executable, '-c', {_CHILD!r}, "
                  f"{os.path.join(_REPO_ROOT, 'prime_sieve')!r}], capture_output=True, text=True); "
                  f"open({log_path!r}, 'a').write(r.stdout + r.stderr); "
                  f"open({exit_path!r}, 'w').write(str(r.returncode))")
        fake = _Fake()

        def reader():
            seen.append(os.path.exists(load_path))
            fake.counters = (fake.counters[0] + 30, fake.counters[1] + 100)
            return fake.counters

        runner = logged_runners.WslLoggedRunner([sys.executable, "-c", script], log_path,
                                                exit_path, queue.Queue())
        runner.read_counters = reader
        output, code = _run(runner)
        match = re.search(r"FIELDS (\{.*\})", output)
        fields = json.loads(match.group(1)) if match else {}
        check(code == 0, f"the run finished ({code}; {output[-300:]})")
        check(fields.get("cpu_busy_during_pct") == "70.0",
              f"the process got its during value from the runner's pairs ({fields})")
        check(len(seen) >= 3, f"the file was updated while the process ran ({len(seen)} writes)")
        check(not os.path.exists(load_path), "the load file is removed at the end")

        quiet_log = os.path.join(folder, "q_1.log")
        quiet_exit = os.path.join(folder, "q_1.exit")
        quiet = logged_runners.WslLoggedRunner(
            [sys.executable, "-c", f"open({quiet_exit!r}, 'w').write('0')"],
            quiet_log, quiet_exit, queue.Queue())
        quiet.read_counters = lambda: None
        _out, quiet_code = _run(quiet)
        check(quiet_code == 0 and not os.path.exists(wsl_command.run_load_path(quiet_log)),
              "no counters -> no load file, the run still finishes")
    finally:
        if env_before is None:
            os.environ.pop(run_load.LOAD_FILE_ENV, None)
        else:
            os.environ[run_load.LOAD_FILE_ENV] = env_before


def _test_app_starts_sampler():
    print("\n--- F. the app starts the sampler ---")
    sys.path.insert(0, _SCRIPT_DIR)
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    try:
        app.update()
        thread = cpu_load._shared._thread
        check(thread is not None and thread.is_alive(), "the sampler thread runs")
        if os.name == "nt":
            time.sleep(2.2)
            before = cpu_load.busy_before_launch()
            check(before is not None and 0 <= before <= 100, f"a before value ({before})")
    finally:
        app.destroy()


def main():
    _test_sampler()
    _test_system_counters()
    _test_machine_id()
    _test_launch_env()
    with tempfile.TemporaryDirectory() as folder:
        _test_runner(folder)
    _test_app_starts_sampler()
    print()
    if failures:
        print(f"{len(failures)} FAILED")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
