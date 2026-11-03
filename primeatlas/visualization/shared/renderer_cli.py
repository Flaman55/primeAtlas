"""
renderer_cli.py -- renderer.py's command line: the shared arguments, every
registered mode's own arguments (VizMode.add_arguments), and the fail-fast
validation that runs before any prime is loaded.
"""

import argparse

from primeatlas.visualization.shared.bigint import parse_big_int
from primeatlas.visualization.shared.playback import _TEMPO_MS_DEFAULT
from primeatlas.visualization.shared.hud_text import _HUD_FONT_SIZE_DEFAULT
from primeatlas.visualization.mode_registry import MODES


def build_parser(description=None):
    """The renderer's argparse parser: the shared arguments and every registered mode's
    own. Also read by tools/gen_design_parameters.py for docs/design/parameters/."""
    from primeatlas.visualization.shared.audio import INSTRUMENTS
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--audio', action='store_true', help='enable optional live sound (requires sounddevice)')
    parser.add_argument('--sound-low', choices=INSTRUMENTS, default='sine')
    parser.add_argument('--sound-prime', choices=INSTRUMENTS, default='triangle')
    parser.add_argument('--sound-lcm', choices=INSTRUMENTS, default='choir')
    # none: no primes at all, for a mode that computes its own data (tree, assembly); opens at --upto.
    parser.add_argument("--source", choices=["synthetic", "sieve", "archive", "none"], default="synthetic")
    parser.add_argument("--count", type=int, default=1_000_000, help="ring count for --source synthetic")
    # Accepts parse_big_int's flexible forms (plain digits, a*10**b, a*10^b,
    # aEb) in addition to a bare int -- see that function's own doc-comment.
    # A real archive floor's own magnitude (floor 25 alone is 26 digits) is
    # exactly why this exists.
    parser.add_argument("--upto", type=parse_big_int, default=1_000_000,
                         help="upper bound for --source sieve/archive -- accepts plain digits, "
                              "a*10**b, a*10^b, or scientific notation (aEb)")
    parser.add_argument("--portal-folder", type=str, default=None, help="PrimeAtlas portal folder for --source archive")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--point-size", type=float, default=3.0)
    # Independent point size for rings ON the vertical reference line
    # (pos["is_hit"] -- real divisors of N), separate from every other
    # ring, e.g. to spot factors of N at a glance without the rest of the
    # field growing too. Defaults to 40
    # so the axis rings are readably distinct even when this flag isn't
    # passed explicitly -- rings_tab.py's own GUI field is pre-filled with
    # "40" to match (see that file's own comment) -- the
    # None-fallback-to-point-size behavior in setup_gl_resources' (gl_setup.py)
    # hit_point_size computation still applies if a caller explicitly passes an
    # empty/omitted value some other way.
    parser.add_argument("--hit-point-size", type=float, default=40.0,
                         help="point size for rings on the vertical reference line "
                              "(divisors of N); defaults to 40.0")
    # Font size (pixels) for the on-canvas HUD text. rasterize_hud_text
    # derives margin/line-spacing from this value too, so scaling it up
    # keeps the whole HUD block proportional instead of just the glyphs.
    parser.add_argument("--hud-font-size", type=int, default=_HUD_FONT_SIZE_DEFAULT,
                         help="pixel size of the on-canvas HUD text, default 35")
    parser.add_argument("--n-step", type=int, default=1000)
    # Load Range -- comma-separated FROM,TO (two non-negative integers,
    # FROM <= TO checked here; the "does TO actually fit under what got
    # loaded" check needs the real loaded `primes` array, so that half
    # happens in renderer_launch.build_session via
    # load_prime_range_slice instead).
    parser.add_argument("--load-range", type=str, default="",
                         help="comma-separated FROM,TO (each accepts plain digits, a*10**b, a*10^b, "
                              "or aEb -- see --upto) -- switch to a fixed range mode showing exactly "
                              "the primes in [FROM,TO], auto-tracking all of them if there aren't too many")
    # Viewing a high floor (e.g. 30) must not require loading every floor
    # below it first. For --source archive with --load-range, this caps how
    # many primes actually get materialized -- see load_archive's own
    # `max_load_count` doc-comment for why it's a plain configurable number
    # here, not a hardcoded guess.
    parser.add_argument("--max-load-count", type=parse_big_int, default=2_000_000,
                         help="safety cap on primes materialized for an archive --load-range load; "
                              "the range is truncated from the top if it holds more than this "
                              "(accepts plain digits, a*10**b, a*10^b, or aEb -- see --upto)")
    # Bidirectional sliding window over --load-range -- OFF by default (enabled
    # explicitly); without it a plain --load-range is a fixed slice of
    # --max-load-count primes.
    parser.add_argument("--slide-load-range", action="store_true",
                         help="--load-range only: instead of a fixed slice stuck wherever "
                              "--max-load-count first landed, keep a bounded chunk that SLIDES "
                              "(both directions) as N/the pattern cursor moves, so the whole "
                              "--load-range span becomes reachable a chunk at a time. Off by "
                              "default -- turn on deliberately, since the extra disk I/O on each "
                              "chunk swap may not suit every machine")
    # `--slide-chunk-size` defaults to None and is resolved to --max-load-count's
    # value right after argument parsing (an explicit --slide-chunk-size still
    # overrides it), so the first chunk and every chunk loaded later by sliding use
    # the same "how much is loaded at once" number unless the user sets them apart.
    # A bigger chunk also means a slower blocking load whenever a swap outruns the
    # background prefetch.
    parser.add_argument("--slide-chunk-size", type=parse_big_int, default=None,
                         help="--slide-load-range only: how many primes each of the back/current/"
                              "forward chunks holds -- defaults to --max-load-count's own value "
                              "when not given, so leaving this blank keeps ONE consistent load size; "
                              "give a real value here to deliberately use a DIFFERENT size while "
                              "sliding than the initial load (accepts plain digits, a*10**b, a*10^b, "
                              "or aEb -- see --upto)")
    # Playback speed -- ports #tempoMs's own default (120ms/tick) and
    # clamp range ([30,2000], see clamp_tempo_ms's own doc-comment); Space
    # starts/stops playback at this rate, ]/[ adjust it live by +/-10ms per
    # press.
    parser.add_argument("--tempo-ms", type=int, default=_TEMPO_MS_DEFAULT,
                         help="playback speed in ms/tick, clamped to [30,2000] "
                              "(Space starts/stops playback, ]/[ adjust it live)")
    # Which viz-mode runs in this window -- see mode_registry.MODES. Each mode adds
    # its own arguments below (VizMode.add_arguments).
    parser.add_argument("--viz-mode", choices=list(MODES), default="rings",
                         help="rings (default): one ring per active small prime, phase = n%%p. "
                              "line: a fixed row of real primes from --load-range, with an optional "
                              "--pattern-seed-k/--pattern-seed-start k-tuple pattern slid along it by N. "
                              "tree: the prime tree on the real n axis (use with --source none). "
                              "assembly: the wheel assembled level by level, q copies of the period "
                              "minus the multiples of q (use with --source none). "
                              "sphere: the first K primes as rings on a sphere through one node, "
                              "N's divisors meet at it (use with --source none; --portal-folder "
                              "gives primality and the prime jumps)")
    # Opt-in live pause/resume protocol -- OFF by default, so running this
    # file directly from a terminal keeps the plain behavior: closing the
    # window (Esc / titlebar X) exits. Only rings_tab.py passes
    # this flag, since it's the only caller that pipes stdin (see
    # LocalLoggedRunner.send_line()) and can actually act on the PAUSED/
    # RESUMED lines this prints -- see start_stdin_command_reader's own
    # doc-comment for the full protocol.
    parser.add_argument("--pipe-stdin-commands", action="store_true",
                         help="read RESUME commands from stdin and, instead of "
                              "exiting on window-close, hide the window and idle "
                              "until one arrives (used by rings_tab.py for live "
                              "pause/resume; harmless but pointless when running "
                              "this file directly from a terminal)")
    for mode_cls in MODES.values():
        mode_cls.add_arguments(parser)
    return parser


def parse_args(description, argv=None):
    """Parses and validates `argv` (sys.argv[1:] when None); `description` is
    the --help text (renderer.py's module docstring). Exits through
    parser.error on an invalid combination."""
    parser = build_parser(description)
    args = parser.parse_args(argv)

    if args.source == "archive" and not args.portal_folder:
        parser.error("--source archive requires --portal-folder")

    # Same fail-fast format validation as the modes' own argument checks:
    # catch a malformed --load-range before renderer.run() ever starts loading
    # primes, rather than raising an uncaught ValueError/unpack error
    # later. The "exceeds what got loaded" case cannot be checked here (no
    # `primes` array yet) -- see
    # renderer_launch.build_session's own call to load_prime_range_slice
    # for that half.
    if args.load_range:
        parts = args.load_range.split(",")
        if len(parts) != 2:
            parser.error(f"--load-range must be exactly two comma-separated FROM,TO values, "
                         f"got {args.load_range!r}")
        try:
            load_from, load_to = (parse_big_int(p) for p in parts)
        except ValueError as e:
            parser.error(f"--load-range: {e}")
        if load_from < 0 or load_to < 0:
            parser.error(f"--load-range FROM/TO must be non-negative, got {args.load_range!r}")
        if load_from > load_to:
            parser.error(f"--load-range FROM must be <= TO, got {args.load_range!r}")

    # Resolve --slide-chunk-size's own inherit-from-max-load-count default
    # (see that argument's own doc-comment above) once, right after
    # parsing -- args.slide_chunk_size is reassigned here so every reader
    # further down (including RenderSession's own construction) sees the
    # already-resolved real number, never has to re-derive the fallback.
    if args.slide_chunk_size is None:
        args.slide_chunk_size = args.max_load_count
    if args.slide_load_range:
        if not args.load_range:
            parser.error("--slide-load-range requires --load-range")
        if args.source != "archive":
            parser.error("--slide-load-range requires --source archive (needs real disk I/O to load neighbor chunks)")
        if not args.slide_chunk_size or args.slide_chunk_size <= 0:
            parser.error(f"--slide-chunk-size (or --max-load-count, its own default source) must be "
                         f"> 0, got {args.slide_chunk_size}")
    for mode_cls in MODES.values():
        mode_cls.validate_arguments(parser, args)
    return args
