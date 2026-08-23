"""
pdf_writer.py -- a minimal, dependency-free PDF writer: just enough (text, lines, filled
shapes, multiple pages) to render this app's reports (the Benchmark tab's growth chart +
full data table, the Constellations tab's records table) into standalone PDF files.

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab backend/
UI split, 2026-08-23) -- this toolkit was already shared by TWO independent renderers
before the split (render_constellation_records_pdf, still in prime_atlas_v1.py, and
render_benchmark_pdf, moved to primeatlas/benchmark.py alongside it), so it gets its own
module instead of living inside either one specifically -- neither renderer "owns" it, and
duplicating it into both would recreate the exact kind of copy-paste this whole refactor
branch exists to undo (see primeatlas/background.py's own docstring for the same reasoning
applied to worker-thread plumbing).

Written by hand instead of pulling in reportlab/matplotlib, to keep this app's documented
zero-extra-installs promise (see prime_atlas_v1.py's module header: "no pip packages
required"). Only the three standard core-14 PDF fonts are used (Helvetica, Helvetica-Bold,
Courier), so no font embedding is needed. WinAnsiEncoding (the default PDF text encoding
for these fonts) doesn't cover Polish diacritics -- static labels drawn via these helpers
stick to plain ASCII; see _pdf_ascii_fold()'s own docstring for how callers handle that.

Pure logic, no tkinter dependency -- exercisable without a display, same as every other
module in this package except settings_tab.py/benchmark_tab.py (see this package's
__init__.py for the general convention).
"""
import math


def _pdf_escape(s):
    return str(s).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


_PDF_ASCII_FOLD_MAP = str.maketrans({
    "ą": "a", "Ą": "A", "ć": "c", "Ć": "C", "ę": "e", "Ę": "E",
    "ł": "l", "Ł": "L", "ń": "n", "Ń": "N", "ó": "o", "Ó": "O",
    "ś": "s", "Ś": "S", "ź": "z", "Ź": "Z", "ż": "z", "Ż": "Z",
})


def _pdf_ascii_fold(text):
    """Strips Polish diacritics down to plain ASCII -- WinAnsiEncoding (the PDF default
    for the core-14 fonts this writer uses, see the module comment above) doesn't cover
    them at all, so a raw accented string would render as garbage/missing glyphs, not
    just "wrong language". Locale strings themselves (strings_pl.json) stay properly
    accented -- they're shared with the on-screen Tkinter UI, which renders UTF-8 fine
    -- this folding only ever happens right here, at the point text is actually drawn
    into a PDF page, for EITHER language. Report chrome (titles/subtitles/continuation
    headers/axis labels) is fully translator-driven and tracks the app's selected
    language -- callers fold the translated string through this function right before
    handing it to _pdf_text_op, so no fixed-language string leaks through untranslated."""
    return text.translate(_PDF_ASCII_FOLD_MAP)


def _pdf_text_op(x, y, size, font_key, text, rgb=(0, 0, 0)):
    r, g, b = rgb
    return (f"{r:.3f} {g:.3f} {b:.3f} rg BT /{font_key} {size} Tf "
            f"1 0 0 1 {x:.2f} {y:.2f} Tm ({_pdf_escape(text)}) Tj ET")


def _pdf_line_op(x1, y1, x2, y2, width=1.0, rgb=(0, 0, 0)):
    r, g, b = rgb
    return (f"{r:.3f} {g:.3f} {b:.3f} RG {width:.2f} w "
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")


def _pdf_rect_op(x, y, w, h, fill_rgb=None, stroke_rgb=None, width=1.0):
    ops = []
    modes = []
    if fill_rgb is not None:
        r, g, b = fill_rgb
        ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
        modes.append("f")
    if stroke_rgb is not None:
        r, g, b = stroke_rgb
        ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {width:.2f} w")
        modes.append("S")
    mode = "B" if len(modes) == 2 else (modes[0] if modes else "n")
    ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re {mode}")
    return " ".join(ops)


def _pdf_dot_op(cx, cy, r, rgb=(0, 0, 0)):
    """Approximates a filled circle with a small octagon -- simpler than a real bezier-curve
    circle in raw PDF content ops, and plenty smooth at chart-marker size (r ~ 2.5pt)."""
    pts = [(cx + r * math.cos(2 * math.pi * i / 8), cy + r * math.sin(2 * math.pi * i / 8))
           for i in range(8)]
    rr, gg, bb = rgb
    parts = [f"{rr:.3f} {gg:.3f} {bb:.3f} rg", f"{pts[0][0]:.2f} {pts[0][1]:.2f} m"]
    for x, y in pts[1:]:
        parts.append(f"{x:.2f} {y:.2f} l")
    parts.append("h f")
    return " ".join(parts)


def _write_pdf(path, pages, page_size=(841.89, 595.28)):
    """Writes a minimal multi-page PDF (PDF 1.4) from `pages` -- a list of lists of raw
    content-stream operator strings (see the _pdf_*_op helpers above), one list per page,
    already positioned in PDF's bottom-left-origin point space. No compression, no font
    embedding -- just objects + an xref table, which is all a plain few-hundred-row report
    needs and keeps the writer itself small enough to read/review in one sitting. Default
    page size is A4 landscape (points, 1pt = 1/72in) -- both current callers' tables have
    enough columns that portrait would force an unreadably small font."""
    width, height = page_size
    objects = {}
    next_id = [1]

    def alloc(body):
        oid = next_id[0]
        next_id[0] += 1
        objects[oid] = body
        return oid

    font_ids = {}
    for name in ("Helvetica", "Helvetica-Bold", "Courier"):
        font_ids[name] = alloc(
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} >>".encode("ascii"))

    pages_id = alloc(None)  # backfilled below, once every page object id is known
    page_ids = []
    for ops in pages:
        content = "\n".join(ops).encode("ascii", errors="replace")
        content_id = alloc(
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream")
        font_res = " ".join(f"/{name} {oid} 0 R" for name, oid in font_ids.items())
        page_id = alloc(
            (f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
             f"/Resources << /Font << {font_res} >> >> /Contents {content_id} 0 R >>"
             ).encode("ascii"))
        page_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
    catalog_id = alloc(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    buf = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for oid in sorted(objects):
        offsets[oid] = len(buf)
        buf += f"{oid} 0 obj\n".encode("ascii")
        buf += objects[oid]
        buf += b"\nendobj\n"
    xref_offset = len(buf)
    total = len(objects) + 1
    buf += f"xref\n0 {total}\n".encode("ascii")
    buf += b"0000000000 65535 f \n"
    for oid in range(1, total):
        buf += f"{offsets[oid]:010d} 00000 n \n".encode("ascii")
    buf += (f"trailer\n<< /Size {total} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF").encode("ascii")

    with open(path, "wb") as f:
        f.write(buf)
