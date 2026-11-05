"""env_versions_view.py -- renders prime_sieve/env_versions.py's JSON report into the
Settings -> WSL environment "Component versions" text and its duplicate-copy warning.
Pure functions, no tkinter, no WSL call.
"""

LIBRARY_LABELS = (("primesieve", "libprimesieve"), ("primecount", "libprimecount"))


def _or_missing(value, T):
    return value if value else T("settings.env_versions_missing")


def _lib_line(label, entry, T):
    if not entry or not entry.get("version"):
        return T("settings.env_versions_line_lib", name=label,
                 version=T("settings.env_versions_missing"), loaded="-")
    return T("settings.env_versions_line_lib", name=label, version=entry["version"],
             loaded=entry.get("loaded") or "-")


def _copy_list(entry):
    return ", ".join(f"{c['path']} ({c['version'] or '?'})" for c in entry["copies"])


def format_report(report, T):
    """(versions text, warning text) for a successful probe report; warning is "" when
    every library has one copy and every engine loads the copy Python loads."""
    lines = [
        T("settings.env_versions_line_distro", distro=_or_missing(report.get("distro"), T)),
        T("settings.env_versions_line_python", python=_or_missing(report.get("python"), T),
          numpy=_or_missing(report.get("numpy"), T)),
    ]
    libs = report.get("libs", {})
    for key, label in LIBRARY_LABELS:
        lines.append(_lib_line(label, libs.get(key), T))
    lines.append(T("settings.env_versions_line_gcc", gcc=_or_missing(report.get("gcc"), T)))

    warnings = []
    for key, label in LIBRARY_LABELS:
        entry = libs.get(key)
        if not entry:
            continue
        if key in report.get("duplicates", []):
            warnings.append(T("settings.env_versions_duplicate", name=label,
                              copies=_copy_list(entry), loaded=entry.get("loaded") or "-"))
        loaded = entry.get("loaded")
        others = sorted(f"{engine} -> {path}" for engine, path in entry["engines"].items()
                        if loaded and path != loaded)
        if others:
            warnings.append(T("settings.env_versions_engines_differ", name=label,
                              loaded=loaded, engines=", ".join(others)))
    return "\n".join(lines), "\n".join(warnings)
