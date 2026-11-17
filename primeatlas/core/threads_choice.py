"""threads_choice -- the text rules of a thread-count field (core/threads_field.py). No tkinter.

A word of the field ("Auto", "Max") is shown with the count it stands for, "Max (8)"; the
field's variable holds the word alone, so a stored value follows the machine it runs on. A
number above the CPU count is turned into the field's `over` word (or the count itself for a
field without words); with the count unknown nothing is turned.
"""
import re

from .number_text import plain_number

CAP = 256  # the list's last number while the CPU count is unknown
_LABEL = re.compile(r"^\s*(.*?)\s*\(\d+\)\s*$")


def label(word, count):
    """`word` with its count, "Max (8)", or the bare word when count is None."""
    return f"{word} ({count})" if count else word


def word_of(text):
    """The text of a label without its count: "Max (8)" -> "Max"; other text stripped."""
    text = str(text or "")
    match = _LABEL.match(text)
    return match.group(1) if match else text.strip()


def fit(text, cpus, over):
    """`text`, or `over` (the count itself when over is None) for a number above `cpus`."""
    if not cpus:
        return text
    raw = plain_number(str(text or ""))
    if raw.isdigit() and int(raw) > cpus:
        return over if over is not None else str(cpus)
    return text


def choices(words, cpus, resolve):
    """The list of a field: each word labelled with resolve(word), then 1..cpus (1..CAP while
    the count is unknown)."""
    return [label(word, resolve(word)) for word in words] + [
        str(n) for n in range(1, (cpus or CAP) + 1)]
