"""Prime numbers -> Storage with D and P windows (storage_kinds.py).

Builds the real app against a temp portal: floor 25 with D windows 0 and 2 and P windows
0 (equal to D) and 1, floor 26 with one P window only. Checks: both floors are listed (a
P-only floor too); an open floor lists D and P files together, sorted by offset, with a
D/P column and the window present in both stores as two rows; after Verify totals a
floor row shows its D total in "Primes" and its P total in a separate "P primes" column,
displayed only while some floor has P primes, while "Files" and "Size" (and the status
bar's disk total) count both stores' files; "Verify P against D" on the active floor
removes the P window equal to its D window, keeps the other, reports the outcome and
refreshes the tree, where the proven D window's D/P column reads "D/P". Windows, real display:
    python unitTests/test_primes_tab_dp.py
"""
import os
import shutil
import sys
import tempfile
import time
import tkinter.messagebox

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

W = 10 ** 7


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def _seed(portal):
    import prime_sieve_v1
    import storage_kinds as sk
    paths = {}
    for floor, idx, kind, offsets in ((25, 0, "D", [37, 39]), (25, 0, "P", [37, 39]),
                                      (25, 1, "P", [3, 9, 21]), (25, 2, "D", [1]),
                                      (26, 0, "P", [7, 9])):
        offset = idx * W
        path = sk.window_path(portal, floor, offset, W, f"{offset // 10 ** 6}M" if offset else "0", kind)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        prime_sieve_v1.write_prime_window(path, [10 ** floor + offset + o for o in offsets])
        paths[(floor, idx, kind)] = path
    return paths


def main():
    portal = tempfile.mkdtemp(prefix="primeatlas_primes_dp_test_")
    shown = []
    tkinter.messagebox.showinfo = lambda *a, **k: shown.append(("info", a))
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(("error", a))
    tkinter.messagebox.askyesno = lambda *a, **k: True
    passed = True
    app = None
    try:
        paths = _seed(portal)
        sys.argv = ["prime_atlas_v2.py"]
        import prime_atlas_v2
        from app_sandbox import isolate_app
        isolate_app(portal)
        app = prime_atlas_v2._build_gui()()
        _pump(app, 3.0)
        widget = app.primes_tab_widget
        nodes = {widget.tree.item(n, "text"): n for n in widget.tree.get_children("")}
        passed &= check(sorted(nodes) == ["10p25", "10p26"],
                        f"D+P floor and P-only floor listed ({sorted(nodes)})")

        node = nodes["10p25"]
        widget.tree.item(node, open=True)
        widget._populate_floor_node(node)
        widget._set_active_floor_node(node)
        rows = [(widget.tree.item(c, "text"), widget.tree.set(c, "kind"))
                for c in widget.tree.get_children(node)]
        passed &= check(rows == [("PRIME_WINDOW_10p25_off_0.bin", "D"),
                                 ("PRIME_WINDOW_10p25_off_0_P.bin", "P"),
                                 ("PRIME_WINDOW_10p25_off_10M_P.bin", "P"),
                                 ("PRIME_WINDOW_10p25_off_20M.bin", "D")],
                        f"file rows sorted by offset with a D/P column ({rows})")
        displayed = tuple(widget.tree.cget("displaycolumns"))
        passed &= check("kind" in displayed and displayed[-1] == "generated",
                        f"D/P column shown with the file rows, generated stays last ({displayed})")

        widget._verify_all_totals()
        _pump(app, 4.0)
        passed &= check(widget.tree.set(node, "count") == "3" and widget.tree.set(node, "p_count") == "5",
                        f"floor 25: D total 3, P total 5 "
                        f"({widget.tree.set(node, 'count')!r}, {widget.tree.set(node, 'p_count')!r})")
        passed &= check(widget.tree.set(nodes["10p26"], "count") in ("0", "")
                        and widget.tree.set(nodes["10p26"], "p_count") == "2",
                        "P-only floor: no D primes, 2 P primes")
        passed &= check("p_count" in tuple(widget.tree.cget("displaycolumns")),
                        "P primes column displayed while a floor has P primes")
        from primeatlas.core.storage import format_bytes
        size = {f: sum(os.path.getsize(path) for (fl, _i, _k), path in paths.items() if fl == f)
                for f in (25, 26)}
        passed &= check(widget.tree.set(node, "files") == "4"
                        and widget.tree.set(node, "size") == format_bytes(size[25]),
                        f"floor 25: Files and Size count D and P files (4, {format_bytes(size[25])}; "
                        f"got {widget.tree.set(node, 'files')!r}, {widget.tree.set(node, 'size')!r})")
        passed &= check(widget.tree.set(nodes["10p26"], "files") == "1"
                        and widget.tree.set(nodes["10p26"], "size") == format_bytes(size[26]),
                        f"P-only floor: Files 1, Size {format_bytes(size[26])} "
                        f"(got {widget.tree.set(nodes['10p26'], 'files')!r}, "
                        f"{widget.tree.set(nodes['10p26'], 'size')!r})")
        status = app.status.get()
        passed &= check(format_bytes(size[25] + size[26]) in status,
                        f"status bar disk total counts both stores "
                        f"({format_bytes(size[25] + size[26])} in {status!r})")
        app.reload_primes_tree()
        _pump(app, 3.0)
        status = app.status.get()
        passed &= check(format_bytes(size[25] + size[26]) in status,
                        f"after a reload too ({format_bytes(size[25] + size[26])} in {status!r})")
        nodes = {widget.tree.item(n, "text"): n for n in widget.tree.get_children("")}
        node = nodes["10p25"]
        passed &= check(widget.tree.set(node, "files") == "4",
                        f"reloaded floor row counts D and P files "
                        f"(got {widget.tree.set(node, 'files')!r})")
        widget.tree.item(node, open=True)
        widget._populate_floor_node(node)
        widget._set_active_floor_node(node)

        shown.clear()
        widget._verify_p_against_d()
        _pump(app, 3.0)
        passed &= check(not os.path.exists(paths[(25, 0, "P")]) and os.path.exists(paths[(25, 1, "P")]),
                        "Verify P against D removes the proven P window, keeps the unproven one")
        passed &= check(shown and shown[-1][0] == "info" and "1" in str(shown[-1][1]),
                        f"outcome reported ({shown[-1] if shown else None})")
        nodes = {widget.tree.item(n, "text"): n for n in widget.tree.get_children("")}
        node = nodes.get("10p25")
        widget.tree.item(node, open=True)
        widget._populate_floor_node(node)
        names = [widget.tree.item(c, "text") for c in widget.tree.get_children(node)]
        passed &= check("PRIME_WINDOW_10p25_off_0_P.bin" not in names,
                        f"tree refreshed after the verify ({names})")
        kinds = {widget.tree.item(c, "text"): widget.tree.set(c, "kind")
                 for c in widget.tree.get_children(node)}
        passed &= check(kinds.get("PRIME_WINDOW_10p25_off_0.bin") == "D/P"
                        and kinds.get("PRIME_WINDOW_10p25_off_20M.bin") == "D",
                        f"proven window shown as D/P ({kinds})")
    finally:
        if app is not None:
            app.destroy()
        shutil.rmtree(portal, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
