"""
test_rings_tab_argv.py -- build_renderer_argv() of
primeatlas/visualization/rings/rings_tab.py: pure argv construction for the ring
renderer subprocess, no tkinter, no app, no display. The RingsTab widget itself is in
test_rings_tab.py.

Usage: python unitTests\\test_rings_tab_argv.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
# primeatlas/__init__.py imports manifest.py, which imports window_sharding --
# needed even just to import primeatlas.visualization.rings.rings_tab for _test_build_renderer_argv
# below.
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_build_renderer_argv():
    from primeatlas.visualization.rings.rings_tab import build_renderer_argv, RENDERER_SCRIPT

    argv = build_renderer_argv("/some/portal", 12345, python_executable="FAKE_PY")
    check(argv[0] == "FAKE_PY", f"argv[0] is the given python_executable (got {argv[0]!r})")
    check(argv[1] == RENDERER_SCRIPT,
          f"argv[1] is the renderer script's PLAIN PATH, not a -m module spec "
          f"(got {argv[1]!r}) -- see renderer.py's own docstring for why -m breaks "
          f"its internal sys.path fix")
    check("--source" in argv and argv[argv.index("--source") + 1] == "archive",
          "argv includes --source archive")
    check("--portal-folder" in argv and argv[argv.index("--portal-folder") + 1] == "/some/portal",
          "argv includes --portal-folder with the given folder")
    check("--upto" in argv and argv[argv.index("--upto") + 1] == "12345",
          "argv includes --upto with the given N as a string")

    default_argv = build_renderer_argv("/x", 1)
    check(default_argv[0] == sys.executable,
          f"python_executable defaults to sys.executable, THIS interpreter, not a bare "
          f"'python' resolved from PATH (got {default_argv[0]!r})")
    check("--windows" not in default_argv,
          f"no --windows arg at all when windows=() (matches renderer.py's own default "
          f"of no highlighting) (got {default_argv!r})")

    # Window-highlight-family argv wiring.
    windows_argv = build_renderer_argv("/x", 1, windows=["bertrand", "legendre"])
    check("--windows" in windows_argv and windows_argv[windows_argv.index("--windows") + 1] == "bertrand,legendre",
          f"--windows joins the given family ids with commas (got {windows_argv!r})")
    check("--general-law-theta" not in windows_argv,
          f"--general-law-theta is omitted when generalLaw isn't among the enabled windows "
          f"(got {windows_argv!r})")

    gl_argv = build_renderer_argv("/x", 1, windows=["generalLaw"], general_law_theta=0.7,
                                   general_law_mode="sliding")
    check("--general-law-theta" in gl_argv and gl_argv[gl_argv.index("--general-law-theta") + 1] == "0.7",
          f"--general-law-theta is included and correct when generalLaw IS enabled (got {gl_argv!r})")
    check("--general-law-mode" in gl_argv and gl_argv[gl_argv.index("--general-law-mode") + 1] == "sliding",
          f"--general-law-mode is included and correct when generalLaw IS enabled (got {gl_argv!r})")

    # point_size argv wiring.
    check("--point-size" not in default_argv,
          f"no --point-size arg at all when point_size=None (matches renderer.py's own "
          f"argparse default) (got {default_argv!r})")
    ps_argv = build_renderer_argv("/x", 1, point_size=12.5)
    check("--point-size" in ps_argv and ps_argv[ps_argv.index("--point-size") + 1] == "12.5",
          f"--point-size is included and correct when a value is given (got {ps_argv!r})")

    # Track P / auto-orbit argv wiring.
    check("--track-primes" not in default_argv,
          f"no --track-primes arg at all when track_primes=() (matches renderer.py's "
          f"own default of no tracking) (got {default_argv!r})")
    check("--auto-orbit" not in default_argv,
          f"no --auto-orbit flag at all when auto_orbit=False (got {default_argv!r})")
    tp_argv = build_renderer_argv("/x", 1, track_primes=["2", "3", "5"])
    check("--track-primes" in tp_argv and tp_argv[tp_argv.index("--track-primes") + 1] == "2,3,5",
          f"--track-primes joins the given values with commas, preserving order "
          f"(got {tp_argv!r})")
    ao_argv = build_renderer_argv("/x", 1, auto_orbit=True)
    check("--auto-orbit" in ao_argv, f"--auto-orbit flag is included when auto_orbit=True (got {ao_argv!r})")
    # Deliberately str(p), not int(p) -- a raw, unvalidated string from the Track P
    # text field must pass through here without raising, even if it's garbage;
    # renderer.py's own --track-primes parsing is where validation happens (same
    # convention as --windows's unknown-family check) -- see build_renderer_argv's
    # own doc-comment for why.
    garbage_argv = build_renderer_argv("/x", 1, track_primes=["2", "not-a-number"])
    check("--track-primes" in garbage_argv and
          garbage_argv[garbage_argv.index("--track-primes") + 1] == "2,not-a-number",
          f"a non-numeric track_primes entry passes through as a plain string instead "
          f"of raising inside the GUI thread (got {garbage_argv!r})")

    # Load Range argv wiring.
    check("--load-range" not in default_argv,
          f"no --load-range arg at all when load_range=None (matches renderer.py's own "
          f"default of sequential mode) (got {default_argv!r})")
    lr_argv = build_renderer_argv("/x", 1, load_range=(100, 500))
    check("--load-range" in lr_argv and lr_argv[lr_argv.index("--load-range") + 1] == "100,500",
          f"--load-range joins the (from, to) pair with a comma (got {lr_argv!r})")

    # max_load_count argv wiring -- same omit-if-None convention as
    # point_size/hit_point_size/hud_font_size.
    check("--max-load-count" not in default_argv,
          f"no --max-load-count arg at all when max_load_count=None (renderer.py's own "
          f"argparse default of 2,000,000 then applies) (got {default_argv!r})")
    mlc_argv = build_renderer_argv("/x", 1, load_range=(100, 500), max_load_count=1000)
    check("--max-load-count" in mlc_argv and mlc_argv[mlc_argv.index("--max-load-count") + 1] == "1000",
          f"--max-load-count forwards a real value as-is (got {mlc_argv!r})")

    # tempo_ms argv wiring -- same omit-if-None convention.
    check("--tempo-ms" not in default_argv,
          f"no --tempo-ms arg at all when tempo_ms=None (renderer.py's own argparse/"
          f"clamp_tempo_ms default of 120 then applies) (got {default_argv!r})")
    tempo_argv = build_renderer_argv("/x", 1, tempo_ms=250)
    check("--tempo-ms" in tempo_argv and tempo_argv[tempo_argv.index("--tempo-ms") + 1] == "250",
          f"--tempo-ms forwards a real value as-is (got {tempo_argv!r})")

    # viz_mode/pattern-seed argv wiring -- "line" viz-mode's k-tuple
    # pattern-slide feature.
    check("--viz-mode" not in default_argv,
          f"no --viz-mode arg at all when viz_mode='rings' (matches renderer.py's own "
          f"default) (got {default_argv!r})")
    line_argv = build_renderer_argv("/x", 1, load_range=(100, 500), viz_mode="line")
    check("--viz-mode" in line_argv and line_argv[line_argv.index("--viz-mode") + 1] == "line",
          f"--viz-mode line is included when requested (got {line_argv!r})")
    check("--pattern-seed-k" not in default_argv and "--pattern-seed-start" not in default_argv,
          f"no --pattern-seed-* args at all when both are None (got {default_argv!r})")
    pattern_argv = build_renderer_argv("/x", 1, load_range=(100, 500), viz_mode="line",
                                        pattern_seed_k=7, pattern_seed_start=11)
    check("--pattern-seed-k" in pattern_argv and pattern_argv[pattern_argv.index("--pattern-seed-k") + 1] == "7",
          f"--pattern-seed-k forwards a real value as-is (got {pattern_argv!r})")
    check("--pattern-seed-start" in pattern_argv and
          pattern_argv[pattern_argv.index("--pattern-seed-start") + 1] == "11",
          f"--pattern-seed-start forwards a real value as-is (got {pattern_argv!r})")

    # Manual/Auto step-mode + MATCH! argv wiring.
    check("--pattern-step-mode" not in default_argv and "--pattern-stop-on-match" not in default_argv,
          f"no --pattern-step-mode/--pattern-stop-on-match args at all with the defaults "
          f"(manual, unchecked) (got {default_argv!r})")
    auto_argv = build_renderer_argv("/x", 1, load_range=(100, 500), viz_mode="line",
                                     pattern_step_mode="auto")
    check("--pattern-step-mode" in auto_argv and auto_argv[auto_argv.index("--pattern-step-mode") + 1] == "auto",
          f"--pattern-step-mode auto is included when requested (got {auto_argv!r})")
    stop_on_match_argv = build_renderer_argv("/x", 1, load_range=(100, 500), viz_mode="line",
                                              pattern_step_mode="auto", pattern_stop_on_match=True)
    check("--pattern-stop-on-match" in stop_on_match_argv,
          f"--pattern-stop-on-match flag is included when checked (got {stop_on_match_argv!r})")

    # Curved-axis argv wiring -- purely visual, same omit-if-False convention.
    check("--line-axis-curved" not in default_argv,
          f"no --line-axis-curved arg at all when unchecked (default) (got {default_argv!r})")
    curved_argv = build_renderer_argv("/x", 1, load_range=(100, 500), viz_mode="line",
                                       line_axis_curved=True)
    check("--line-axis-curved" in curved_argv,
          f"--line-axis-curved flag is included when checked (got {curved_argv!r})")

    # Sliding-window argv wiring -- default OFF, same omit-if-default convention as
    # line_axis_curved above.
    check("--slide-load-range" not in default_argv,
          f"no --slide-load-range arg at all when unchecked (default) (got {default_argv!r})")
    slide_argv = build_renderer_argv("/x", 1, load_range=(100, 500), slide_load_range=True)
    check("--slide-load-range" in slide_argv,
          f"--slide-load-range flag is included when checked (got {slide_argv!r})")
    check("--slide-chunk-size" not in default_argv and "--slide-chunk-size" not in slide_argv,
          f"no --slide-chunk-size arg at all when slide_chunk_size=None, even with sliding "
          f"itself turned on (renderer.py's own argparse default then applies) "
          f"(got {slide_argv!r})")
    slide_chunk_argv = build_renderer_argv("/x", 1, load_range=(100, 500), slide_load_range=True,
                                            slide_chunk_size=50000)
    check("--slide-chunk-size" in slide_chunk_argv and
          slide_chunk_argv[slide_chunk_argv.index("--slide-chunk-size") + 1] == "50000",
          f"--slide-chunk-size forwards a real value as-is (got {slide_chunk_argv!r})")

    # hit_point_size/hud_font_size argv wiring, mirroring point_size's own
    # omit-if-None convention exactly. renderer.py's own argparse defaults
    # are 40.0 / 35 -- this test only checks build_renderer_argv's own
    # function-level default (None omits the flag from argv); the
    # actual numeric value that then applies lives in renderer.py's
    # argparse, not here.
    check("--hit-point-size" not in default_argv,
          f"no --hit-point-size arg at all when hit_point_size=None (renderer.py's own "
          f"argparse default of 40.0 then applies) (got {default_argv!r})")
    check("--hud-font-size" not in default_argv,
          f"no --hud-font-size arg at all when hud_font_size=None (renderer.py's own "
          f"argparse default of 35px then applies) (got {default_argv!r})")
    hps_argv = build_renderer_argv("/x", 1, hit_point_size=8.0)
    check("--hit-point-size" in hps_argv and hps_argv[hps_argv.index("--hit-point-size") + 1] == "8.0",
          f"--hit-point-size is included and correct when a value is given (got {hps_argv!r})")
    hfs_argv = build_renderer_argv("/x", 1, hud_font_size=32)
    check("--hud-font-size" in hfs_argv and hfs_argv[hfs_argv.index("--hud-font-size") + 1] == "32",
          f"--hud-font-size is included and correct when a value is given (got {hfs_argv!r})")


def main():
    _test_build_renderer_argv()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
