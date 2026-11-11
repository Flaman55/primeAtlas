"""A table heading wrapped to its column, and the column width that fits it.

wrap(): the text's words on greedy lines no wider than the width (a newline always breaks; a
word wider than the width stands alone). min_width(): the narrowest width at which the text
takes at most max_lines lines, so a long heading over short values makes the cell taller, not
the column wider. fit_width(): a column's width, the wider of its widest cell and its heading's
min_width, plus padding. `measure` gives a string's width in pixels (a tkinter Font's measure).
No tkinter here.
"""

MAX_LINES = 2


def wrap(text, width, measure):
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if line and measure(candidate) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
    return lines


def min_width(text, measure, max_lines=MAX_LINES):
    """The narrowest width at which wrap() gives at most `max_lines` lines; 0 for blank text."""
    words = text.split()
    if not words:
        return 0
    # The answer is the width of some run of consecutive words, never below the widest word
    # (it would overflow its cell): try them narrowest first.
    widest_word = max(map(measure, words))
    candidates = sorted({w for i in range(len(words)) for j in range(i + 1, len(words) + 1)
                         if (w := measure(" ".join(words[i:j]))) >= widest_word})
    return next(w for w in candidates if len(wrap(text, w, measure)) <= max_lines)


def fit_width(heading, cells, measure, padding, heading_measure=None, max_lines=MAX_LINES):
    """Width of a column showing `cells` under `heading`: the widest cell or the heading's
    min_width, whichever is wider, plus `padding`. `heading_measure` measures the heading
    (its font may differ from the cells'); `measure` when omitted."""
    widest = max((measure(cell) for cell in cells), default=0)
    return max(widest, min_width(heading, heading_measure or measure, max_lines)) + padding
