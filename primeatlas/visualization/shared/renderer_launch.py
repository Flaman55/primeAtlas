"""
renderer_launch.py -- the launch half of renderer.py that needs no GL: loads the
prime array for --source, applies --load-range, lets every registered mode turn its
own CLI arguments into its RenderSession config, and builds the RenderSession the
window and main loop then drive.
"""

import time
from types import SimpleNamespace

from primeatlas.visualization.shared.bigint import parse_big_int
from primeatlas.visualization.shared.sources import load_synthetic, load_sieve, load_archive, load_none
from primeatlas.visualization.shared.range_data import load_prime_range_slice, initial_n_for_source
from primeatlas.visualization.shared.draw_primitives import _FIT_MARGIN
from primeatlas.visualization.shared.playback import _RANGE_STEP_ORBIT_TICKS
from primeatlas.visualization.shared.session import RenderSession
from primeatlas.visualization.shared.mode import LaunchAborted
from primeatlas.visualization.mode_registry import MODES


def build_session(args):
    """Loads the primes and builds the RenderSession for the parsed arguments.
    Returns None when a mode refuses to open the window (LaunchAborted); its
    message is already printed."""
    # For --source sieve/archive, the view OPENS exactly at N=args.upto (see
    # initial_n_for_source's own docstring) -- but sequential playback needs
    # somewhere to advance TO, and loading only up to that exact N leaves
    # zero headroom: N would already equal the load ceiling on frame one, so
    # Space would silently refuse to start every time. `load_upto` pads
    # the underlying LOAD by a modest +5% (at least 1000) past the
    # requested N so there is room to play forward and actually see
    # auto-orbit cycle; the DISPLAY still opens at the user's exact
    # args.upto below (n = initial_n_for_source(..., args.upto, ...), not
    # load_upto) -- only the loaded prime array itself is padded.
    load_upto = args.upto
    if args.source in ("sieve", "archive"):
        load_upto = args.upto + max(1000, args.upto // 20)

    # For --source archive with an explicit --load-range, loading [0,
    # load_upto] in full before load_range's post-hoc slice runs is
    # infeasible once the requested range sits at a high floor, since every
    # floor below it
    # would be read first for nothing. Loading directly via `from_n=FROM`
    # instead reuses load_archive's own already-existing cheap floor-skip
    # (see that function's own `from_n` doc-comment) to jump straight to the
    # requested floor, capped by --max-load-count so an accidentally huge
    # span still can't stall the whole load (truncated from the top -- see
    # load_archive's own doc-comment on that point). `primes` IS the range
    # here already, so the load_range block further below (which slices
    # synthetic/sieve out of the full load) is told to skip its own
    # redundant re-slice via `archive_range_preload`.
    archive_range_preload = None
    if args.source == "archive" and args.load_range:
        archive_range_preload = tuple(parse_big_int(p) for p in args.load_range.split(","))

    print(f"Loading primes via --source={args.source} ...")
    t0 = time.perf_counter()
    if args.source == "none":
        primes = load_none()
    elif args.source == "synthetic":
        primes = load_synthetic(args.count)
    elif args.source == "sieve":
        primes = load_sieve(load_upto)
    elif args.source == "archive":
        if archive_range_preload is not None:
            preload_from, preload_to = archive_range_preload
            primes = load_archive(args.portal_folder, preload_to, from_n=preload_from,
                                   max_load_count=args.max_load_count)
        else:
            primes = load_archive(args.portal_folder, load_upto)
    else:
        raise ValueError(f"unknown --source {args.source!r}")
    t1 = time.perf_counter()
    print(f"Loaded {len(primes):,} values in {t1 - t0:.2f}s")

    n = initial_n_for_source(args.source, args.upto, primes)
    # See fit_zoom_for_viewport's own doc-comment for why this uses the
    # shared _FIT_MARGIN constant rather than a second, independent 0.45
    # literal -- it keeps "the view as it opens" and "the view after an
    # explicit re-fit (F11 / middle-click)" provably the same computation.
    max_radius = min(args.width, args.height) * _FIT_MARGIN

    # Playback state -- ports #isRunning, #tempoMs,
    # #autoOrbitIndex/#autoOrbitCounter/#trackedPrimes (the auto-orbit
    # half). `ceiling` mirrors the JS's own PrimeDataSource ceiling check
    # inside #tick/#toggleRunning (sequential mode only -- range mode has no
    # ceiling, same as tick_next_n/can_start_playback's own `range_mode`
    # bypass).
    #
    # `ceiling` must be load_upto, not `int(primes[-1])` (the largest ACTUAL
    # prime found): the real boundary of trustworthy data is how far
    # loading went, not where the last prime happened to land (primes can
    # be sparse near the boundary, e.g. load_upto=100 with primes[-1]=97
    # would wrongly refuse 3 perfectly safe ticks). Using load_upto also
    # gives the load-time headroom padding above something real to advance
    # into instead of refusing on frame one.
    ceiling = load_upto if args.source in ("sieve", "archive") else (int(primes[-1]) if len(primes) else -1)

    # Reuses the same margin figure as load_upto's own launch-time pad just
    # above, instead of inventing a second, different margin concept.
    #
    # Scoped to --source archive only: synthetic/sieve are both bounded by
    # their own launch-time argument with nothing further to ever fetch
    # (see load_archive's own module-level docstring point 1) -- archive is
    # the one real, always-possibly-larger data source this module has (a
    # disk portal that can simply have more window files than were loaded
    # at launch). See RenderSession.extend_buffer_if_needed for the
    # actual extension call.
    buffer_margin = max(1000, args.upto // 20)
    can_extend_buffer = args.source == "archive" and bool(args.portal_folder)
    # Extension-exhausted, tempo/playback, orbit and cyclic-anchor state are
    # RenderSession fields (self.extend_exhausted, self.tempo_ms/playback_running,
    # self.orbit_*, self.cyclic_anchor_state), constructed further down once
    # `range_mode`/`range_primes`/`range_step`/`track_primes`/`auto_orbit` below are
    # known -- see session.py's RenderSession docstring.

    # Load Range -- ports #loadPrimeRange: switch
    # to a FIXED ring set (range_primes), independent of N from here on
    # (rebuild_buffer below uses it verbatim instead of `primes[primes <=
    # n_value]` whenever range_mode is True -- see load_prime_range_slice's
    # own doc-comment for why `primes` itself is the ceiling here, unlike
    # the JS's separate always-larger PrimeDataSource). Failures are
    # reported the same friendly way the JS's #loadPrimeRange does (a plain
    # printed line, this module's only "info" surface -- see
    # hud_lines_for_n's own doc-comment for why stdout and not a GL overlay)
    # rather than crashing the whole subprocess over a bad --load-range.
    range_mode = False
    range_primes = None
    # Range mode's per-tick N-advance, dynamically sized to the largest
    # currently-loaded prime once range_primes is known below; stays at
    # this default (1) for sequential mode and for a range that fails to
    # load at all -- see tick_next_n's own doc-comment for the full
    # rationale.
    range_step = 1
    if args.load_range:
        load_from, load_to = (parse_big_int(p) for p in args.load_range.split(","))
        try:
            if archive_range_preload is not None:
                # `primes` was already loaded directly as this exact (possibly
                # --max-load-count-truncated) range above -- re-slicing it
                # here would be redundant, and load_prime_range_slice's own
                # "does TO fit under what got loaded" check would wrongly
                # raise whenever truncation legitimately left primes[-1]
                # short of load_to.
                range_primes = primes
            else:
                range_primes = load_prime_range_slice(primes, load_from, load_to)
            range_mode = True
            n = 0  # mirrors the JS's own `this.#n = 0` on a successful range load
            range_count = len(range_primes)
            # Without this, playback would look frozen at a real
            # archive-floor-scale range, since a fixed step of 1 is
            # imperceptible against prime gaps of that size. See
            # tick_next_n's own doc-comment -- naturally settles back to `1`
            # at low floors (where a full orbit already fits inside
            # _RANGE_STEP_ORBIT_TICKS).
            if range_count:
                range_step = max(1, int(range_primes[-1]) // _RANGE_STEP_ORBIT_TICKS)
            # A range of at most 500 primes is tracked in full by the rings mode
            # (see RingMode.prepare_launch).
            if 0 < range_count <= 500:
                print(f"Range [{load_from:,}, {load_to:,}] loaded: {range_count:,} primes, all tracked")
            elif range_count and int(range_primes[-1]) < load_to:
                print(f"Range [{load_from:,}, {load_to:,}] capped at --max-load-count="
                      f"{args.max_load_count:,}: only [{load_from:,}, {int(range_primes[-1]):,}] "
                      f"loaded ({range_count:,} primes)")
            else:
                print(f"Range [{load_from:,}, {load_to:,}] loaded: {range_count:,} primes")
        except ValueError as e:
            print(f"Load Range failed: {e}")

    # Each registered mode turns its own CLI arguments into its RenderSession
    # config (every mode's config is needed: reset() returns to the rings mode).
    # A mode may move the opening N (line mode's pattern anchor) or refuse to
    # open the window (LaunchAborted).
    launch = SimpleNamespace(primes=primes, n=n, range_mode=range_mode, range_primes=range_primes)
    mode_config = {}
    try:
        for mode_cls in MODES.values():
            mode_config.update(mode_cls.prepare_launch(args, launch))
    except LaunchAborted as e:
        print(e)
        return
    n = launch.n

    # Everything from here down operates on one RenderSession object (see
    # session.py); `session.n` is the current N, and every GLFW callback and the main
    # loop below call session.* methods.
    session = RenderSession(
        primes=primes, n=n, ceiling=ceiling, range_mode=range_mode,
        range_primes=range_primes, range_step=range_step,
        max_radius=max_radius, tempo_ms=args.tempo_ms,
        buffer_margin=buffer_margin, can_extend_buffer=can_extend_buffer,
        portal_folder=args.portal_folder,
        viz_mode=args.viz_mode,
        range_load_from=load_from if range_mode else None,
        range_load_to=load_to if range_mode else None,
        chunk_size=args.slide_chunk_size, sliding_enabled=args.slide_load_range,
        **mode_config,
    )
    return session
