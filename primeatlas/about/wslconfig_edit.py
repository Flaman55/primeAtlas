"""
wslconfig_edit.py -- how Atlas changes the WSL limits: memory= (RAM) and processors= (CPU
threads) of the [wsl2] section of %UserProfile%\\.wslconfig (system_info.wslconfig_path()).
No admin rights: the file belongs to the user. No tkinter.

  - min_limit_gib(ram)          the smallest RAM limit offered: WSL's own default, half the RAM
  - proposed_limit_gib(ram)     Windows RAM minus a reserve for Windows, whole GiB
  - max_limit_gib(ram)          the largest RAM limit offered: the whole GiB of Windows RAM
  - is_risky(gib, ram)          a RAM limit above the proposal, which Save warns about
  - max_processors(threads)     the largest processor limit: every Windows thread, WSL's default
  - set_wsl2_keys(text, values) the file's text with only the given [wsl2] keys changed
  - plan_change / apply_change  read, diff, write with a backup next to the file
  - shutdown_wsl()              `wsl.exe --shutdown`: a new limit applies on WSL's next start

The reserve (RESERVE_SHARE of the RAM, at least RESERVE_MIN_GIB) is an arbitrary default:
the proposal only fills the field, the user types any limit within min_limit_gib()..
max_limit_gib(). Below WSL's default a limit only starves WSL, so it is not offered.
"""
import difflib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime

GIB = 1024 ** 3
RESERVE_SHARE = 0.25
RESERVE_MIN_GIB = 3
WSL_DEFAULT_SHARE = 0.5  # what WSL takes with no memory= set
MIN_LIMIT_GIB = 1
MIN_PROCESSORS = 1
SHUTDOWN_TIMEOUT_S = 60
BACKUP_SUFFIX_FORMAT = ".bak_%Y-%m-%d_%H%M%S"
_BOM = b"\xef\xbb\xbf"
_SECTION = re.compile(r"^\s*\[\s*([^\]]*?)\s*\]")
# key, value, trailing spaces/comment, line end; the value is what changes.
_KEY_LINE = r"^(\s*{key}\s*=\s*)([^#\r\n]*?)(\s*(?:#[^\r\n]*)?)(\r?\n)?$"


class FileChangedError(OSError):
    """The file changed between plan_change() and apply_change()."""


def min_limit_gib(ram_bytes):
    if not ram_bytes:
        return None
    return max(MIN_LIMIT_GIB, round(WSL_DEFAULT_SHARE * ram_bytes / GIB))


def proposed_limit_gib(ram_bytes):
    if not ram_bytes:
        return None
    reserve = max(RESERVE_MIN_GIB * GIB, RESERVE_SHARE * ram_bytes)
    return max(min_limit_gib(ram_bytes), round((ram_bytes - reserve) / GIB))


def max_limit_gib(ram_bytes):
    if not ram_bytes:
        return None
    return max(MIN_LIMIT_GIB, ram_bytes // GIB)


def is_risky(gib, ram_bytes):
    """True when `gib` leaves Windows less than the proposal's reserve."""
    proposal = proposed_limit_gib(ram_bytes)
    return proposal is not None and gib > proposal


def max_processors(threads):
    return threads or None


def _is_key_line(line):
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith(("#", ";", "["))


def set_wsl2_keys(text, values):
    """`text` with every [wsl2] line of each key of `values` (key -> value text) set to its
    value; a missing key is added after the last key of [wsl2], in the order of `values`."""
    if not values:
        return text
    newline = "\r\n" if "\r\n" in text else "\n"
    patterns = {key: re.compile(_KEY_LINE.format(key=re.escape(key)), re.I) for key in values}
    lines = text.splitlines(keepends=True)
    section = None
    header = None      # index of the [wsl2] header line
    last_key = None    # index of the last key line of [wsl2]
    found = set()
    for i, line in enumerate(lines):
        match = _SECTION.match(line)
        if match:
            section = match.group(1).lower()
            if section == "wsl2" and header is None:
                header = i
            continue
        if section != "wsl2":
            continue
        for key, pattern in patterns.items():
            match = pattern.match(line)
            if match:
                lines[i] = match.group(1) + values[key] + match.group(3) + (match.group(4) or "")
                found.add(key)
        if _is_key_line(line):
            last_key = i
    new_lines = "".join(f"{key}={value}{newline}" for key, value in values.items()
                        if key not in found)
    if not new_lines:
        return "".join(lines)
    if header is None:
        if not lines:
            return f"[wsl2]{newline}{new_lines}"
        if not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        return "".join(lines) + f"{newline}[wsl2]{newline}{new_lines}"
    after = last_key if last_key is not None else header
    if not lines[after].endswith(("\n", "\r")):
        lines[after] += newline
    lines.insert(after + 1, new_lines)
    return "".join(lines)


@dataclass(frozen=True)
class WslconfigChange:
    path: str
    old_bytes: bytes   # None when the file does not exist
    old_text: str
    new_text: str
    bom: bool

    @property
    def existed(self):
        return self.old_bytes is not None

    @property
    def changed(self):
        return not self.existed or self.new_text != self.old_text

    def with_values(self, values):
        """The change from the same old file to its text with `values` set (set_wsl2_keys)."""
        return replace(self, new_text=set_wsl2_keys(self.old_text, values))

    def diff_lines(self):
        """"- old line" / "+ new line" for each line removed or added, in file order."""
        if not self.changed:
            return []
        diff = difflib.unified_diff(self.old_text.splitlines(), self.new_text.splitlines(),
                                    lineterm="", n=0)
        return [f"{line[0]} {line[1:]}" for line in diff
                if line[:1] in "+-" and not line.startswith(("+++", "---"))]


def _read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


def plan_change(path, values):
    """The change setting the [wsl2] keys of the file at `path` to `values` (key -> value
    text); nothing is written. {} plans no change and reads the file's current text."""
    old = _read_bytes(path)
    bom = old is not None and old.startswith(_BOM)
    text = "" if old is None else old[len(_BOM) if bom else 0:].decode("utf-8")
    return WslconfigChange(path, old, text, set_wsl2_keys(text, values), bom)


def apply_change(change, now=None):
    """Writes the planned text and returns the backup's path (None for a new file or no
    change). The old file is copied first; the new text replaces it in one rename, so the
    file is never half written. Raises FileChangedError when the file is no longer what was
    planned against, OSError when it cannot be written."""
    if not change.changed:
        return None
    if _read_bytes(change.path) != change.old_bytes:
        raise FileChangedError(change.path)
    backup = None
    if change.existed:
        backup = change.path + (now or datetime.now()).strftime(BACKUP_SUFFIX_FORMAT)
        shutil.copy2(change.path, backup)
    data = (_BOM if change.bom else b"") + change.new_text.encode("utf-8")
    folder = os.path.dirname(os.path.abspath(change.path))
    handle, temp = tempfile.mkstemp(dir=folder, prefix=".wslconfig.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(data)
        os.replace(temp, change.path)
    except BaseException:
        if os.path.exists(temp):
            os.remove(temp)
        raise
    return backup


def shutdown_wsl(run=subprocess.run, timeout=SHUTDOWN_TIMEOUT_S):
    """`wsl.exe --shutdown` (stops every WSL distro); True when it reported success."""
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        result = run(["wsl.exe", "--shutdown"], capture_output=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
