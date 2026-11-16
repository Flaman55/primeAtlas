"""
windows_hardware.py -- the Windows side of the computer Atlas runs on: OS, CPU model,
physical cores, threads, RAM total and free. Read in this process with no admin rights and
without WSL; a value that cannot be read is None, never a guess.
"""
import ctypes
import os
import platform
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowsInfo:
    os_name: str = None
    cpu_model: str = None
    cores: int = None
    threads: int = None
    ram_total: int = None
    ram_free: int = None


def _os_name():
    if os.name != "nt":
        return platform.platform() or None
    release, version, _sp, _type = platform.win32_ver()
    edition = platform.win32_edition() or ""
    name = " ".join(part for part in ("Windows", release, edition) if part)
    return f"{name} ({version})" if version else name


def _cpu_model():
    if os.name != "nt":
        return platform.processor() or None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return " ".join(str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).split()) or None
    except OSError:
        return None


def _physical_cores():
    """One SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX record per core (RelationProcessorCore)."""
    if os.name != "nt":
        return None
    relation_processor_core = 0
    kernel32 = ctypes.windll.kernel32
    length = ctypes.c_ulong(0)
    kernel32.GetLogicalProcessorInformationEx(relation_processor_core, None, ctypes.byref(length))
    if not length.value:
        return None
    buffer = ctypes.create_string_buffer(length.value)
    if not kernel32.GetLogicalProcessorInformationEx(relation_processor_core, buffer,
                                                     ctypes.byref(length)):
        return None
    cores = offset = 0
    while offset + 8 <= length.value:
        size = int.from_bytes(buffer.raw[offset + 4:offset + 8], "little")
        if size <= 0:
            break
        cores += 1
        offset += size
    return cores or None


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def windows_ram():
    """(total, free) physical RAM of Windows in bytes, (None, None) when unreadable."""
    if os.name != "nt":
        return None, None
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, None
    return status.ullTotalPhys, status.ullAvailPhys


def read_windows_info():
    total, free = windows_ram()
    return WindowsInfo(os_name=_os_name(), cpu_model=_cpu_model(), cores=_physical_cores(),
                       threads=os.cpu_count(), ram_total=total, ram_free=free)
