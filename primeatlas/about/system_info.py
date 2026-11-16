"""
system_info.py -- what the About tab reads about the computer Atlas runs on: Windows
(core.windows_hardware), WSL as the sieve sees it (distro, kernel, CPUs, MemTotal,
MemAvailable) and the [wsl2] limits of %UserProfile%\\.wslconfig.

Every probe is best effort and needs no admin rights: a value that cannot be read is
None, never a guess. read_system_info() starts WSL when it is not running, so callers run
it off the Tk thread (core.background) and only when the user asks to see it.
"""
import os
import re
import subprocess
from dataclasses import dataclass

from primeatlas.core.windows_hardware import WindowsInfo, read_windows_info

WSL_PROBE_TIMEOUT_S = 20
# One wsl.exe call: key=value lines, the two /proc/meminfo lines and os-release's name.
WSL_PROBE = ('echo "nproc=$(nproc)"; echo "kernel=$(uname -r)"; '
             "grep -E '^(MemTotal|MemAvailable):' /proc/meminfo; "
             "grep '^PRETTY_NAME=' /etc/os-release")
_SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*([KMGT]?)B?")
_UNIT = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}

__all__ = ["WindowsInfo", "WslInfo", "WslConfig", "SystemInfo", "parse_size", "parse_wslconfig",
           "parse_wsl_probe", "wslconfig_path", "read_wslconfig", "read_wsl_info",
           "read_windows_info", "read_system_info"]


@dataclass(frozen=True)
class WslInfo:
    distro: str = None
    kernel: str = None
    cpus: int = None
    mem_total: int = None
    mem_available: int = None


@dataclass(frozen=True)
class WslConfig:
    memory_text: str = None
    memory_bytes: int = None
    processors: int = None


@dataclass(frozen=True)
class SystemInfo:
    windows: WindowsInfo
    wsl: WslInfo  # None when WSL cannot be reached
    wslconfig: WslConfig


def parse_size(text):
    """A .wslconfig size ("56GB", "512MB", "8G", "1073741824") in bytes, 1024-based; None
    when `text` is not one."""
    if text is None:
        return None
    match = _SIZE.fullmatch(str(text).strip().upper())
    if not match:
        return None
    return int(float(match.group(1)) * _UNIT[match.group(2)])


def parse_wslconfig(text):
    """memory= (text and bytes) and processors= of the [wsl2] section of .wslconfig text."""
    section = None
    values = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
        elif section == "wsl2" and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip().lower()] = value.strip()
    memory = values.get("memory") or None
    processors = values.get("processors", "")
    return WslConfig(memory_text=memory, memory_bytes=parse_size(memory),
                     processors=int(processors) if processors.isdigit() else None)


def parse_wsl_probe(text):
    """WslInfo from the output of WSL_PROBE; a missing or broken line leaves its field None."""
    fields = {}
    for line in text.splitlines():
        if line.startswith(("nproc=", "kernel=")):
            key, value = line.split("=", 1)
            fields[key] = value.strip()
        elif line.startswith("PRETTY_NAME="):
            fields["distro"] = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith(("MemTotal:", "MemAvailable:")):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                fields[parts[0].rstrip(":")] = int(parts[1]) * 1024  # /proc/meminfo is in kB
    cpus = fields.get("nproc", "")
    return WslInfo(distro=fields.get("distro") or None, kernel=fields.get("kernel") or None,
                   cpus=int(cpus) if cpus.isdigit() and int(cpus) > 0 else None,
                   mem_total=fields.get("MemTotal"), mem_available=fields.get("MemAvailable"))


def wslconfig_path():
    return os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), ".wslconfig")


def read_wslconfig(path=None):
    try:
        with open(path or wslconfig_path(), encoding="utf-8-sig") as f:
            return parse_wslconfig(f.read())
    except (OSError, UnicodeDecodeError):
        return WslConfig()


def read_wsl_info(timeout=WSL_PROBE_TIMEOUT_S):
    """WslInfo of the default distro, or None when WSL cannot be reached."""
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        result = subprocess.run(["wsl.exe", "-e", "bash", "-c", WSL_PROBE],
                                capture_output=True, text=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return parse_wsl_probe(result.stdout)


def read_system_info():
    """Everything at once; slow (starts WSL when it is not running), run it in the background."""
    return SystemInfo(read_windows_info(), read_wsl_info(), read_wslconfig())
