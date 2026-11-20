"""
system_info_text.py -- the About tab's "This computer" lines from a system_info.SystemInfo:
Windows (OS, CPU, RAM, the computer's id in benchmark rows), WSL (distro, kernel, what it sees) and the WSL RAM limit as a share
of the Windows RAM with where it comes from (.wslconfig memory= or the WSL default);
a CPU details line right under the CPU line and a RAM details line right under the RAM line,
from the CPU/RAM details (SystemInfo.details) completed by the values typed for this computer
in benchmark_machines.json (architecture, release year and turbo in the CPU line, CL and
XMP/EXPO in the RAM line; a value not typed is left out). A value that could not be read
shows as "unknown".
"""
from ..core import number_format
from ..core.hardware_details import HardwareDetails

GIB = 1024 ** 3


def gib_text(value, T):
    return f"{number_format.decimal(value / GIB, 1)} GiB" if value else T("about.system_unknown")


def _known(value, T):
    return value if value else T("about.system_unknown")


def _cache(kb, T):
    if not kb:
        return T("about.system_unknown")
    return f"{number_format.whole(kb // 1024)} MB" if kb % 1024 == 0 else f"{number_format.whole(kb)} KB"


def _memory_kind(details, T):
    if details.ram_type and details.ram_mts:
        return f"{details.ram_type}-{details.ram_mts}"
    if details.ram_mts:
        return f"{number_format.whole(details.ram_mts)} MT/s"
    return details.ram_type or T("about.system_unknown")


def _mhz(value, T):
    return f"{number_format.whole(value)} MHz" if value else T("about.system_unknown")


def details_lines(details, manual, T):
    """The CPU details line and the RAM details line of hardware_details.HardwareDetails
    completed by the typed values `manual` (machines_file.MANUAL_FIELDS, None = not typed);
    none when nothing is known or typed."""
    if details is None:
        details = HardwareDetails()
    if not any(vars(details).values()) and all(v is None for v in manual.values()):
        return None
    cpu = []
    if manual.get("architecture") is not None:
        cpu.append(str(manual["architecture"]))
    if manual.get("year") is not None:
        cpu.append(T("about.system_released", year=manual["year"]))
    cpu.append(T("about.system_base", base=_mhz(details.base_mhz, T)))
    if manual.get("turbo_mhz") is not None:
        cpu.append(T("about.system_turbo", turbo=_mhz(manual["turbo_mhz"], T)))
    cpu += [f"L2 {_cache(details.l2_kb, T)}", f"L3 {_cache(details.l3_kb, T)}",
            _known(details.cpu_family, T)]
    ram = [T("about.system_ram_size", size=gib_text(details.ram_bytes, T),
             modules=_known(details.ram_modules, T)), _memory_kind(details, T)]
    if manual.get("cl") is not None:
        ram.append(f"CL {manual['cl']}")
    if manual.get("xmp") is not None:
        ram.append(T("about.system_xmp",
                     xmp=T("machine.xmp_on") if manual["xmp"] else T("machine.xmp_off")))
    return (T("about.system_cpu_details", parts=", ".join(cpu)),
            T("about.system_ram_details", parts=", ".join(ram)))


def system_info_lines(info, T, machine=None):
    """The lines of `info` with its CPU/RAM details completed by the typed values of
    `machine` (this computer's entry of benchmark_machines.json, None for none)."""
    lines = _windows_wsl_lines(info, T)
    extra = details_lines(info.details, (machine or {}).get("manual") or {}, T)
    if extra is not None:
        cpu_line, ram_line = extra
        lines.insert(2, cpu_line)
        lines.insert(4, ram_line)
    return lines


def _windows_wsl_lines(info, T):
    w, wsl, cfg = info.windows, info.wsl, info.wslconfig
    lines = [
        T("about.system_windows", os=_known(w.os_name, T)),
        T("about.system_cpu", model=_known(w.cpu_model, T), cores=_known(w.cores, T),
          threads=_known(w.threads, T)),
        T("about.system_ram", total=gib_text(w.ram_total, T), free=gib_text(w.ram_free, T)),
        T("about.system_machine_id", machine_id=_known(w.machine_id, T)),
    ]
    if wsl is None:
        lines.append(T("about.system_wsl_unreachable"))
        return lines
    lines.append(T("about.system_wsl", distro=_known(wsl.distro, T), kernel=_known(wsl.kernel, T)))
    resources = T("about.system_wsl_resources", cpus=_known(wsl.cpus, T),
                  total=gib_text(wsl.mem_total, T), available=gib_text(wsl.mem_available, T))
    if cfg.processors:
        resources += T("about.system_processors_config", processors=cfg.processors)
    lines.append(resources)
    source = (T("about.system_limit_config", memory=cfg.memory_text) if cfg.memory_text
              else T("about.system_limit_default"))
    if wsl.mem_total and w.ram_total:
        lines.append(T("about.system_wsl_limit", limit=gib_text(wsl.mem_total, T),
                       share=round(100 * wsl.mem_total / w.ram_total), source=source))
    else:
        lines.append(T("about.system_wsl_limit_no_share", limit=gib_text(wsl.mem_total, T),
                       source=source))
    return lines
