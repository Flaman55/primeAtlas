"""
system_info_text.py -- the About tab's "This computer" lines from a system_info.SystemInfo:
Windows (OS, CPU, RAM, the computer's id in benchmark rows), WSL (distro, kernel, what it sees) and the WSL RAM limit as a share
of the Windows RAM with where it comes from (.wslconfig memory= or the WSL default).
A value that could not be read shows as "unknown".
"""
GIB = 1024 ** 3


def _gib(value, T):
    return f"{value / GIB:.1f} GiB" if value else T("about.system_unknown")


def _known(value, T):
    return value if value else T("about.system_unknown")


def system_info_lines(info, T):
    w, wsl, cfg = info.windows, info.wsl, info.wslconfig
    lines = [
        T("about.system_windows", os=_known(w.os_name, T)),
        T("about.system_cpu", model=_known(w.cpu_model, T), cores=_known(w.cores, T),
          threads=_known(w.threads, T)),
        T("about.system_ram", total=_gib(w.ram_total, T), free=_gib(w.ram_free, T)),
        T("about.system_machine_id", machine_id=_known(w.machine_id, T)),
    ]
    if wsl is None:
        lines.append(T("about.system_wsl_unreachable"))
        return lines
    lines.append(T("about.system_wsl", distro=_known(wsl.distro, T), kernel=_known(wsl.kernel, T)))
    resources = T("about.system_wsl_resources", cpus=_known(wsl.cpus, T),
                  total=_gib(wsl.mem_total, T), available=_gib(wsl.mem_available, T))
    if cfg.processors:
        resources += T("about.system_processors_config", processors=cfg.processors)
    lines.append(resources)
    source = (T("about.system_limit_config", memory=cfg.memory_text) if cfg.memory_text
              else T("about.system_limit_default"))
    if wsl.mem_total and w.ram_total:
        lines.append(T("about.system_wsl_limit", limit=_gib(wsl.mem_total, T),
                       share=round(100 * wsl.mem_total / w.ram_total), source=source))
    else:
        lines.append(T("about.system_wsl_limit_no_share", limit=_gib(wsl.mem_total, T),
                       source=source))
    return lines
