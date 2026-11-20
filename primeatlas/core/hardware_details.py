"""
hardware_details.py -- the CPU and RAM details Windows gives without admin rights, read by one
hidden PowerShell Get-CimInstance call: CPU model, maker, family text, physical cores,
threads, base clock, L2/L3; RAM installed size, module count, type and configured speed.
Turbo clock, release year, CL timings and the XMP/EXPO switch need a driver or the firmware,
so they are typed by the person (machines_file.MANUAL_FIELDS). Serial and part numbers are
never read. A value that cannot be read is None, never a guess.

read_hardware_details() takes about a second (PowerShell start), so the app runs it in the
background (core.hardware_dynamic).
"""
import json
import os
import subprocess
from dataclasses import dataclass

CIM_TIMEOUT_S = 30
CIM_SCRIPT = (
    "$c=@(Get-CimInstance Win32_Processor | Select-Object Name,Manufacturer,Caption,"
    "NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,L2CacheSize,L3CacheSize);"
    "$m=@(Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,"
    "ConfiguredClockSpeed,Speed,SMBIOSMemoryType);"
    "@{cpu=$c;ram=$m} | ConvertTo-Json -Depth 3 -Compress")

# SMBIOS memory type codes (SMBIOS 3.x, Type 17); other codes are unknown.
MEMORY_TYPES = {24: "DDR3", 26: "DDR4", 30: "LPDDR4", 34: "DDR5", 35: "LPDDR5"}
# The fastest standard JEDEC speed grade of each desktop type, in MT/s: a configured speed
# above it comes from a memory profile (XMP/EXPO) or a manual overclock.
JEDEC_MAX_MTS = {"DDR3": 2133, "DDR4": 3200, "DDR5": 8800}


@dataclass(frozen=True)
class HardwareDetails:
    cpu_name: str = None
    cpu_maker: str = None
    cpu_family: str = None
    cores: int = None
    threads: int = None
    base_mhz: int = None
    l2_kb: int = None
    l3_kb: int = None
    ram_bytes: int = None
    ram_type: str = None
    ram_mts: int = None
    ram_modules: int = None


def _list(value):
    if isinstance(value, dict):
        return [value]
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return int(value)


def _text(value):
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    return text or None


def _sum(values):
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def parse_cim_json(text):
    """HardwareDetails from CIM_SCRIPT's output; every field None for anything unreadable."""
    try:
        data = json.loads(text or "")
    except ValueError:
        return HardwareDetails()
    if not isinstance(data, dict):
        return HardwareDetails()
    cpus, modules = _list(data.get("cpu")), _list(data.get("ram"))
    first = cpus[0] if cpus else {}
    kinds = {MEMORY_TYPES.get(_positive(m.get("SMBIOSMemoryType"))) for m in modules}
    configured = [s for s in (_positive(m.get("ConfiguredClockSpeed")) for m in modules) if s]
    rated = [s for s in (_positive(m.get("Speed")) for m in modules) if s]
    speeds = configured or rated
    return HardwareDetails(
        cpu_name=_text(first.get("Name")), cpu_maker=_text(first.get("Manufacturer")),
        cpu_family=_text(first.get("Caption")),
        cores=_sum(_positive(c.get("NumberOfCores")) for c in cpus),
        threads=_sum(_positive(c.get("NumberOfLogicalProcessors")) for c in cpus),
        base_mhz=_positive(first.get("MaxClockSpeed")), l2_kb=_positive(first.get("L2CacheSize")),
        l3_kb=_positive(first.get("L3CacheSize")),
        ram_bytes=_sum(_positive(m.get("Capacity")) for m in modules),
        ram_type=kinds.pop() if len(kinds) == 1 else None,
        ram_mts=min(speeds) if speeds else None,
        ram_modules=len(modules) or None)


def xmp_hint(ram_type, mts):
    """The JEDEC maximum of `ram_type` when the configured speed `mts` is above it (a memory
    profile is likely on), else None."""
    top = JEDEC_MAX_MTS.get(ram_type)
    return top if top and mts and mts > top else None


def read_hardware_details(run=subprocess.run, timeout=CIM_TIMEOUT_S):
    """HardwareDetails of this computer; every field None off Windows or when PowerShell
    fails, times out or exits with an error. Never raises."""
    if os.name != "nt":
        return HardwareDetails()
    try:
        result = run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", CIM_SCRIPT],
                     capture_output=True, text=True, timeout=timeout,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return HardwareDetails()
    if result.returncode != 0:
        return HardwareDetails()
    return parse_cim_json(result.stdout)
