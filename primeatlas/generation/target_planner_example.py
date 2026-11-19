"""The target planner's example list: target_planner_example.txt next to this module is the one
text Insert example puts into the targets field, and ensure_copy() puts a copy of it into the
storage folder, where Load file opens, so the file form is there to look at and edit. An
existing copy is the person's and is never overwritten. No tkinter.
"""
import os

EXAMPLE_FILE_NAME = "target_planner_example.txt"
_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), EXAMPLE_FILE_NAME)


def example_text():
    """The example list, without its trailing newline."""
    with open(_SOURCE, encoding="utf-8") as f:
        return f.read().rstrip("\n")


def ensure_copy(storage):
    """The path of the example copy in `storage`, written first when missing; None when it
    cannot be written (the caller goes on without it)."""
    path = os.path.join(storage, EXAMPLE_FILE_NAME)
    if os.path.isfile(path):
        return path
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as f:
            f.write(example_text() + "\n")
    except OSError:
        return None
    return path
