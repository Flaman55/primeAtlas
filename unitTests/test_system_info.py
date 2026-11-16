"""
test_system_info.py -- what Atlas reads about the computer it runs on (About -> This computer).

A. primeatlas/about/system_info.py parsers:
   parse_size: a .wslconfig size ("56GB", "512mb", "8G", "1.5GB", "1073741824") in bytes,
   1024-based, case and spaces ignored; anything else (empty, negative, unknown unit,
   "abc") is None.
   parse_wslconfig: memory= and processors= of the [wsl2] section only (keys and section
   names in any case, "#"/";" comments and inline "#" comments ignored, the last value of
   a repeated key wins, values of other sections never leak in); missing keys are None.
   parse_wsl_probe: the WSL probe's output gives distro, kernel, CPUs, MemTotal and
   MemAvailable in bytes; missing or broken lines give None for that field only; empty
   output gives every field None.
B. The live Windows probe (primeatlas/core/windows_hardware.py): threads equal
   os.cpu_count(), physical cores are between 1 and the threads, total RAM is positive and
   free RAM is below it, the OS and CPU model are non-empty text. wslconfig_path() is
   .wslconfig in the user's profile folder.
C. primeatlas/about/system_info_text.py: system_info_lines(info, T) names the OS, the CPU
   with cores and threads, Windows RAM total and free, the WSL distro and kernel, what WSL
   sees (CPUs, RAM, available) and the WSL RAM limit as a share of Windows RAM with its
   source: .wslconfig memory= when set, else the WSL default of half the Windows RAM; an
   unreachable WSL gives one line saying so and no limit line; unknown values read
   "unknown", never 0 or a made-up number. The computer's id (the machine_id of its
   benchmark rows) is shown too; the live probe reads windows_hardware.this_machine_id().

Usage:
    python unitTests/test_system_info.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []
GIB = 1024 ** 3


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_parsers():
    print("\n--- A. parsers ---")
    from primeatlas.about import system_info as si
    for text, want in (("56GB", 56 * GIB), ("512mb", 512 * 1024 ** 2), ("8G", 8 * GIB),
                       (" 1.5 GB ", int(1.5 * GIB)), ("1073741824", GIB), ("2TB", 2 * 1024 ** 4),
                       ("64KB", 64 * 1024), ("100B", 100)):
        got = si.parse_size(text)
        check(got == want, f"parse_size({text!r}) == {want} (got {got})")
    for text in ("", "abc", "-4GB", "4XB", "GB", "4 G B", None):
        check(si.parse_size(text) is None, f"parse_size({text!r}) is None")

    cfg = si.parse_wslconfig(
        "# my settings\n"
        "[experimental]\nmemory=1GB\nprocessors=1\n"
        "[WSL2]\n; note\nMemory = 48GB   # leave room for Windows\nprocessors=8\n"
        "memory=56GB\n"
        "[other]\nprocessors=2\n")
    check(cfg.memory_text == "56GB" and cfg.memory_bytes == 56 * GIB,
          f"[wsl2] memory=: last value wins, comments and other sections ignored ({cfg})")
    check(cfg.processors == 8, f"[wsl2] processors= is read, other sections ignored ({cfg})")
    empty = si.parse_wslconfig("[wsl2]\nswap=0\n")
    check(empty.memory_text is None and empty.memory_bytes is None and empty.processors is None,
          f"missing keys are None ({empty})")
    bad = si.parse_wslconfig("[wsl2]\nmemory=lots\nprocessors=many\n")
    check(bad.memory_text == "lots" and bad.memory_bytes is None and bad.processors is None,
          f"an unreadable memory= keeps its text, its size is None ({bad})")
    check(si.parse_wslconfig("memory=8GB\n").memory_text is None,
          "a key outside any section is not [wsl2]'s")

    probe = ("nproc=24\nkernel=6.6.87.2-microsoft-standard-WSL2\n"
             "MemTotal:       57585296 kB\nMemAvailable:   55000000 kB\n"
             'PRETTY_NAME="Ubuntu 24.04.1 LTS"\n')
    wsl = si.parse_wsl_probe(probe)
    check(wsl.cpus == 24 and wsl.kernel == "6.6.87.2-microsoft-standard-WSL2"
          and wsl.distro == "Ubuntu 24.04.1 LTS", f"probe: CPUs, kernel, distro ({wsl})")
    check(wsl.mem_total == 57585296 * 1024 and wsl.mem_available == 55000000 * 1024,
          f"probe: MemTotal and MemAvailable in bytes ({wsl})")
    part = si.parse_wsl_probe("nproc=x\nkernel=\nMemTotal: 1000 kB\n")
    check(part.cpus is None and part.kernel is None and part.distro is None
          and part.mem_total == 1024000 and part.mem_available is None,
          f"broken or missing lines give None for that field only ({part})")
    none = si.parse_wsl_probe("")
    check(all(v is None for v in (none.cpus, none.kernel, none.distro, none.mem_total,
                                  none.mem_available)), f"empty output: all None ({none})")


def _test_live_windows():
    print("\n--- B. live Windows probe ---")
    from primeatlas.about import system_info as si
    if os.name != "nt":
        print("SKIPPED (Windows-only)")
        return
    w = si.read_windows_info()
    check(w.threads == os.cpu_count(), f"threads == os.cpu_count() ({w.threads})")
    check(w.cores is not None and 1 <= w.cores <= w.threads,
          f"physical cores between 1 and the threads ({w.cores})")
    from primeatlas.core import windows_hardware
    check(w.machine_id == windows_hardware.this_machine_id() and w.machine_id,
          f"the computer's id is the benchmark rows' id ({w.machine_id})")
    check(w.ram_total and w.ram_total > 0 and w.ram_free is not None
          and 0 <= w.ram_free < w.ram_total, f"RAM total > free >= 0 ({w.ram_total}, {w.ram_free})")
    check(bool(w.os_name) and bool(w.cpu_model), f"OS and CPU model are named ({w.os_name!r}, "
                                                 f"{w.cpu_model!r})")
    want = os.path.join(os.path.expanduser("~"), ".wslconfig")
    check(os.path.normcase(si.wslconfig_path()) == os.path.normcase(want),
          f"wslconfig_path() is {want} ({si.wslconfig_path()})")


def _test_text():
    print("\n--- C. system_info_lines ---")
    from primeatlas.about import system_info as si
    from primeatlas.core.i18n import Translator
    from primeatlas.about.system_info_text import system_info_lines
    for lang in ("en", "pl"):
        T = Translator(lang)
        windows = si.WindowsInfo(os_name="Windows 11 Professional (10.0.26200)",
                                 cpu_model="Test CPU 9000", cores=12, threads=24,
                                 ram_total=64 * GIB, ram_free=40 * GIB,
                                 machine_id="3f9a0c1d2e4b")
        wsl = si.WslInfo(distro="Ubuntu 24.04.1 LTS", kernel="6.6.87.2-microsoft-standard-WSL2",
                         cpus=24, mem_total=48 * GIB, mem_available=46 * GIB)
        set_cfg = si.WslConfig(memory_text="48GB", memory_bytes=48 * GIB, processors=None)
        lines = system_info_lines(si.SystemInfo(windows, wsl, set_cfg), T)
        text = "\n".join(lines)
        for needle in ("Windows 11 Professional (10.0.26200)", "Test CPU 9000", "12", "24",
                       "64.0 GiB", "40.0 GiB", "Ubuntu 24.04.1 LTS",
                       "6.6.87.2-microsoft-standard-WSL2", "48.0 GiB", "46.0 GiB", "75 %",
                       "memory=48GB", "3f9a0c1d2e4b"):
            check(needle in text, f"[{lang}] lines show {needle!r}")
        check(not any(k in text for k in ("about.", "{", "}")), f"[{lang}] no raw keys ({text!r})")

        default = system_info_lines(si.SystemInfo(windows, si.WslInfo(
            distro="Ubuntu", kernel="k", cpus=24, mem_total=32 * GIB, mem_available=30 * GIB),
            si.WslConfig(None, None, None)), T)
        dtext = "\n".join(default)
        check("50 %" in dtext and "memory=" not in dtext
              and T("about.system_limit_default") in dtext,
              f"[{lang}] no memory=: the limit names the WSL default ({default[-1]!r})")

        down = system_info_lines(si.SystemInfo(windows, None, set_cfg), T)
        check(T("about.system_wsl_unreachable") in down
              and not any("%" in line for line in down),
              f"[{lang}] unreachable WSL: one line saying so, no limit line ({down})")

        blank = si.WindowsInfo(os_name=None, cpu_model=None, cores=None, threads=None,
                               ram_total=None, ram_free=None)
        unknown = system_info_lines(si.SystemInfo(blank, wsl, set_cfg), T)
        utext = "\n".join(unknown)
        check(T("about.system_unknown") in utext and " 0 " not in utext and "0.0 GiB" not in utext,
              f"[{lang}] unknown values read unknown, never 0 ({unknown})")
        check(not any("%" in line for line in unknown),
              f"[{lang}] no share of an unknown Windows RAM ({unknown})")


def main():
    _test_parsers()
    _test_live_windows()
    _test_text()


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  FAIL: {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
