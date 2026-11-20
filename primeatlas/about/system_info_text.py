"""
system_info_text.py -- the About tab's "This computer" lines from a system_info.SystemInfo:
Windows (OS, CPU, RAM, the computer's id in benchmark rows), WSL (distro, kernel, what it sees) and the WSL RAM limit as a share
of the Windows RAM with where it comes from (.wslconfig memory= or the WSL default);
with the CPU/RAM details (SystemInfo.details) a CPU line and a RAM line, and with this
computer's entry of benchmark_machines.json the values typed in its window ("not typed" for
an empty one). A value that could not be read shows as "unknown".
"""
from ..core import number_format

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


def details_lines(details, T):
    """The CPU and RAM lines of hardware_details.HardwareDetails; none when nothing is known."""
    if details is None or not any(vars(details).values()):
        return []
    base = (f"{number_format.whole(details.base_mhz)} MHz" if details.base_mhz
            else T("about.system_unknown"))
    return [T("about.system_cpu_details", base=base, l2=_cache(details.l2_kb, T),
              l3=_cache(details.l3_kb, T), family=_known(details.cpu_family, T)),
            T("about.system_ram_details", size=gib_text(details.ram_bytes, T),
              modules=_known(details.ram_modules, T), kind=_memory_kind(details, T))]


def typed_line(manual, T):
    """The values typed in the machine window (machines_file.MANUAL_FIELDS)."""
    def shown(value, text=str):
        return T("about.system_not_typed") if value is None else text(value)
    return T("about.system_typed", architecture=shown(manual.get("architecture")),
             year=shown(manual.get("year")),
             turbo=shown(manual.get("turbo_mhz"), lambda v: f"{number_format.whole(v)} MHz"),
             cl=shown(manual.get("cl")),
             xmp=shown(manual.get("xmp"),
                       lambda v: T("machine.xmp_on") if v else T("machine.xmp_off")))


def system_info_lines(info, T, machine=None):
    """The lines of `info`, then its CPU/RAM details and the typed values of `machine` (this
    computer's entry of benchmark_machines.json, None for none)."""
    lines = _windows_wsl_lines(info, T) + details_lines(info.details, T)
    if machine is not None:
        lines.append(typed_line(machine.get("manual") or {}, T))
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
