"""
test_hardware_details.py -- the CPU and RAM details Windows gives without admin rights
(primeatlas/core/hardware_details.py), read by PowerShell Get-CimInstance.

A. parse_cim_json(text):
   - CPU: model, maker, family text ("AMD64 Family 25 Model 33 Stepping 2"), physical cores,
     threads, base clock (MaxClockSpeed, MHz), L2 and L3 (KB); two sockets sum cores and
     threads and keep the first model;
   - RAM: installed capacity = the sum of the modules, the module count, the type from
     SMBIOSMemoryType (24 DDR3, 26 DDR4, 30 LPDDR4, 34 DDR5, 35 LPDDR5; any other code is
     unknown), the speed = the lowest ConfiguredClockSpeed of the modules (mixed modules run
     at the slowest), Speed when no module reports a configured one;
   - one module or one CPU given as an object instead of a list reads the same;
   - a missing, zero or non-number value is None, never 0 or a guess; serial numbers and
     part numbers are never kept (no such field exists);
   - empty text, broken JSON or JSON of another shape gives every field None.
B. xmp_hint(ram_type, mts): the JEDEC maximum of that type (DDR3 2133, DDR4 3200,
   DDR5 8800) when the configured speed is above it, else None (at the maximum, below it,
   unknown type, unknown speed).
C. read_hardware_details(run=...): runs PowerShell once, hidden, with a time limit, and parses
   its output; a failing run (OSError, time limit, non-zero exit) gives every field None
   and never raises. Off Windows it runs nothing.
D. Live, on Windows: the read gives a CPU model, cores between 1 and threads, and RAM at least
   the Windows total RAM less 10 % (firmware reserves a part of the installed RAM).

Usage:
    python unitTests/test_hardware_details.py
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


GB = 1024 ** 3
CPU = {"Name": "AMD Ryzen 9 5900X 12-Core Processor            ", "Manufacturer": "AuthenticAMD",
       "Caption": "AMD64 Family 25 Model 33 Stepping 2", "NumberOfCores": 12,
       "NumberOfLogicalProcessors": 24, "MaxClockSpeed": 3701, "L2CacheSize": 6144,
       "L3CacheSize": 65536}


def module(capacity=16 * GB, configured=3600, speed=3600, kind=26):
    return {"Capacity": capacity, "ConfiguredClockSpeed": configured, "Speed": speed,
            "SMBIOSMemoryType": kind}


def parse_checks(hd):
    passed = True
    d = hd.parse_cim_json(json.dumps({"cpu": [CPU], "ram": [module()] * 4}))
    passed &= check((d.cpu_name, d.cpu_maker, d.cpu_family, d.cores, d.threads, d.base_mhz,
                     d.l2_kb, d.l3_kb) == ("AMD Ryzen 9 5900X 12-Core Processor", "AuthenticAMD",
                                           "AMD64 Family 25 Model 33 Stepping 2", 12, 24, 3701,
                                           6144, 65536),
                    f"CPU fields, model without trailing spaces ({d})")
    passed &= check((d.ram_bytes, d.ram_modules, d.ram_type, d.ram_mts)
                    == (64 * GB, 4, "DDR4", 3600), "RAM: 4 x 16 GB DDR4-3600")
    names = set(vars(d)) if hasattr(d, "__dict__") else set(d.__dataclass_fields__)
    passed &= check(not any("serial" in n or "part" in n for n in names),
                    f"no serial or part number field ({sorted(names)})")

    one = hd.parse_cim_json(json.dumps({"cpu": CPU, "ram": module(8 * GB)}))
    passed &= check((one.cpu_name, one.cores, one.ram_bytes, one.ram_modules)
                    == ("AMD Ryzen 9 5900X 12-Core Processor", 12, 8 * GB, 1),
                    "one CPU and one module as objects read the same")

    two = hd.parse_cim_json(json.dumps({"cpu": [CPU, dict(CPU, Name="Other")], "ram": []}))
    passed &= check((two.cpu_name, two.cores, two.threads, two.ram_bytes, two.ram_modules)
                    == ("AMD Ryzen 9 5900X 12-Core Processor", 24, 48, None, None),
                    "two sockets sum cores/threads, keep the first model; no modules: None")

    mixed = hd.parse_cim_json(json.dumps(
        {"cpu": [CPU], "ram": [module(configured=3200), module(configured=3600)]}))
    passed &= check(mixed.ram_mts == 3200, f"mixed modules: the slowest ({mixed.ram_mts})")
    fallback = hd.parse_cim_json(json.dumps(
        {"cpu": [CPU], "ram": [module(configured=0, speed=2666), module(configured=None,
                                                                        speed=3200)]}))
    passed &= check(fallback.ram_mts == 2666, f"no configured speed: Speed ({fallback.ram_mts})")

    for code, name in ((24, "DDR3"), (26, "DDR4"), (30, "LPDDR4"), (34, "DDR5"),
                       (35, "LPDDR5"), (0, None), (2, None), (None, None)):
        got = hd.parse_cim_json(json.dumps({"cpu": [], "ram": [module(kind=code)]})).ram_type
        passed &= check(got == name, f"SMBIOSMemoryType {code} -> {name} ({got})")
    mixed_kind = hd.parse_cim_json(json.dumps({"cpu": [], "ram": [module(kind=26),
                                                                  module(kind=34)]}))
    passed &= check(mixed_kind.ram_type is None, "modules of two types: type unknown")

    blank = hd.parse_cim_json(json.dumps({"cpu": [{"Name": "  ", "NumberOfCores": 0,
                                                   "MaxClockSpeed": "fast", "L3CacheSize": -1}],
                                          "ram": [{"Capacity": "x"}]}))
    passed &= check((blank.cpu_name, blank.cores, blank.base_mhz, blank.l3_kb, blank.ram_bytes,
                     blank.ram_mts) == (None,) * 6,
                    f"blank, zero, negative and non-number values are None ({blank})")
    empty = hd.HardwareDetails()
    for text in ("", "not json", "[1, 2]", json.dumps({"cpu": "x", "ram": 5}), "null"):
        passed &= check(hd.parse_cim_json(text) == empty, f"{text!r}: every field None")
    return passed


def hint_checks(hd):
    passed = True
    for kind, mts, expected in (("DDR4", 3600, 3200), ("DDR4", 3200, None),
                                ("DDR4", 2666, None), ("DDR3", 2400, 2133), ("DDR5", 9600, 8800),
                                ("DDR5", 6000, None), ("LPDDR5", 9000, None), (None, 3600, None),
                                ("DDR4", None, None)):
        got = hd.xmp_hint(kind, mts)
        passed &= check(got == expected, f"xmp_hint({kind}, {mts}) = {expected} ({got})")
    return passed


def read_checks(hd):
    passed = True
    calls = []
    good = json.dumps({"cpu": [CPU], "ram": [module()]})

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=good, stderr="")

    details = hd.read_hardware_details(run=run)
    if os.name == "nt":
        argv, kwargs = calls[0] if calls else ([], {})
        passed &= check(len(calls) == 1 and "powershell" in str(argv[0]).lower()
                        and kwargs.get("timeout") and kwargs.get("creationflags"),
                        f"one hidden PowerShell run with a time limit ({calls})")
        passed &= check(details.cpu_name == "AMD Ryzen 9 5900X 12-Core Processor",
                        "its output parsed")
    else:
        passed &= check(not calls and details == hd.HardwareDetails(), "off Windows: no run")

    def failing(error):
        def run_fail(argv, **kwargs):
            if isinstance(error, int):
                return subprocess.CompletedProcess(argv, error, stdout=good, stderr="")
            raise error
        return run_fail

    for error in (OSError("no powershell"), subprocess.TimeoutExpired("powershell", 1), 1):
        try:
            got = hd.read_hardware_details(run=failing(error))
            passed &= check(got == hd.HardwareDetails(), f"{error!r}: every field None")
        except Exception as raised:  # noqa: BLE001
            passed &= check(False, f"{error!r} raised {raised!r}")
    return passed


def live_checks(hd):
    if os.name != "nt":
        print("SKIPPED live read (Windows only)")
        return True
    from primeatlas.core.windows_hardware import windows_ram
    d = hd.read_hardware_details()
    total, _free = windows_ram()
    return check(d.cpu_name and d.cores and d.threads and 1 <= d.cores <= d.threads
                 and d.ram_bytes and d.ram_bytes >= 0.9 * total,
                 f"live: {d.cpu_name}, {d.cores}/{d.threads}, RAM {d.ram_bytes} vs {total}")


def main():
    from primeatlas.core import hardware_details as hd
    passed = parse_checks(hd)
    passed &= hint_checks(hd)
    passed &= read_checks(hd)
    passed &= live_checks(hd)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
