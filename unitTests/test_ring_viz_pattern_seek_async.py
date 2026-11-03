"""
test_ring_viz_pattern_seek_async.py -- the sliding-window pattern seek of RenderSession
(session.py) running on a background thread: the main thread is never blocked, further
navigation input is ignored while a seek is in flight, the HUD shows "searching",
not-found outcomes, a reset discarding a stale result, an exception not wedging the
seek thread, and the bigger search stride that recenters to the chunk size.

No moderngl/glfw import anywhere -- same "pure logic, GPU-free" convention as every
other ring_viz test in this folder.

Usage: python unitTests\\test_ring_viz_pattern_seek_async.py
"""
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from ring_viz_fixtures import sieve_primes_upto, write_floor  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


# ---------------------------------------------------------------------------
# Background pattern seek: with chunk_size=500 and a sparse k=5 pattern the next
# MATCH! can be MANY chunk crossings away, each a blocking disk load, which would
# freeze the GLFW window if _pattern_seek ran synchronously on the main thread.
# See session.py's _start_pattern_seek doc-comment for the design.
# ---------------------------------------------------------------------------

def _test_sliding_seek_runs_in_background_not_blocking_main_thread():
    """The actual async contract this feature exists for: scrub_advance()
    (or bump_n/tick) returns almost instantly even while the underlying
    multi-chunk crawl is artificially slowed down, self.n stays untouched
    until the background search resolves, and joining the thread afterward
    still reaches the same correct match this file's own synchronous
    _test_sliding_forward_multi_chunk_seek_finds_distant_match already
    proves for the DATA side -- same fixture (target=359, 6 real chunk
    crossings away)."""
    from primeatlas.visualization.shared import session as session_module
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive
    import time

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        real_load_archive = session_module.load_archive
        slow_delay = 0.2

        def _slow_load_archive(*args, **kwargs):
            time.sleep(slow_delay)
            return real_load_archive(*args, **kwargs)

        session_module.load_archive = _slow_load_archive
        try:
            t0 = time.perf_counter()
            session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
            elapsed = time.perf_counter() - t0
            check(elapsed < slow_delay,
                  f"scrub_advance returns almost instantly even though the underlying multi-chunk "
                  f"crawl needs several {slow_delay}s-slow loads (got {elapsed:.3f}s)")
            check(session._seek_thread is not None, "the seek is genuinely still running in the background")
            check(session.n == start_n, "self.n is untouched while the background search is still in flight")

            session._seek_thread.join(timeout=10)
            check(session._seek_thread is None, "the seek thread clears itself once the search resolves")
            check(session.n == target,
                  f"the background search still reaches the correct real match (expected {target}, got {session.n})")
        finally:
            session_module.load_archive = real_load_archive
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_ignores_further_nav_input_while_in_flight():
    """No true cancellation in v1 (see _start_pattern_seek's own
    doc-comment) -- a second nav call arriving while a seek is already
    running must be a pure no-op, not start a second, concurrent thread
    (chunk_back/chunk_current/chunk_forward have no locking of their own).
    Proven by identity-checking that _seek_thread stays the SAME thread
    object across the extra calls, and that self.n stays untouched until
    the one real seek eventually resolves."""
    from primeatlas.visualization.shared import session as session_module
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive
    import time

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        real_load_archive = session_module.load_archive
        slow_delay = 0.2

        def _slow_load_archive(*args, **kwargs):
            time.sleep(slow_delay)
            return real_load_archive(*args, **kwargs)

        session_module.load_archive = _slow_load_archive
        try:
            session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
            first_thread = session._seek_thread
            check(first_thread is not None, "test setup: the first seek is running")

            session.bump_n(50)
            session.scrub_advance(is_right=False, ctrl_held=False, is_first_press=True)
            check(session._seek_thread is first_thread,
                  "extra nav input while a seek is in flight is ignored -- no second thread is started")
            check(session.n == start_n, "n stays untouched by the ignored extra input")

            first_thread.join(timeout=10)
            check(session.n == target,
                  f"the original (only) seek still resolves correctly once the extra input was ignored "
                  f"(expected {target}, got {session.n})")
        finally:
            session_module.load_archive = real_load_archive
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_hud_shows_searching_while_in_flight():
    """rebuild_line's own edge_lines addition must surface a "Searching..."
    line while _seek_thread is running, and it must disappear again once
    the search resolves -- a background search is only actually reassuring
    (versus looking frozen) if the user can SEE it's working."""
    from primeatlas.visualization.shared import session as session_module
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive
    import time

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        real_load_archive = session_module.load_archive
        slow_delay = 0.2

        def _slow_load_archive(*args, **kwargs):
            time.sleep(slow_delay)
            return real_load_archive(*args, **kwargs)

        session_module.load_archive = _slow_load_archive
        try:
            session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
            check(session._seek_thread is not None, "test setup: the seek is in flight")
            session.rebuild(session.n)
            check(any("Searching" in line for line in session.hud_lines),
                  f"the HUD shows a searching indicator while the seek is running (got {session.hud_lines!r})")

            session._seek_thread.join(timeout=10)
            session.rebuild(session.n)
            check(not any("Searching" in line for line in session.hud_lines),
                  f"the searching indicator disappears again once the seek resolves (got {session.hud_lines!r})")
        finally:
            session_module.load_archive = real_load_archive
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_tick_not_found_stops_playback_in_background():
    """tick()'s own not-found stop (stop playback + print) must still happen
    when sliding moves the search to a
    background thread -- just a frame or more later, once the worker
    itself resolves. Reuses the same "no real [0,2] match anywhere, real
    range_load_to edge" fixture as
    _test_sliding_found_false_means_true_range_edge_not_chunk_edge."""
    import contextlib
    import io
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 30)]  # 1..175, no real [0,2] match anywhere
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        session.playback_running = True

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            stopped = session.tick()
            check(stopped is False,
                  "tick() never synchronously reports 'stopped' once sliding is on -- the background "
                  "worker owns that decision now")
            check(session._seek_thread is not None, "test setup: the search moved to a background thread")
            check(session.playback_running is True, "playback still looks 'running' while the search is in flight")
            session._seek_thread.join(timeout=10)
        out = buf.getvalue()
        check(session.playback_running is False,
              "the background worker itself stops playback once it confirms the genuine range edge, "
              "with no further match found")
        check(session.n == start_n, "n is left untouched -- no non-match candidate is ever committed")
        check("Playback stopped" in out, f"a message explaining the stop still gets printed (got {out!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_bump_and_scrub_not_found_leave_n_unchanged_async():
    """bump_n/scrub_advance's own found-gated commit (self.n = new_n only
    if found) still holds once the search is backgrounded -- reuses the
    same real-edge, no-match fixture as the tick() test above, exercised
    via both entry points."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 30)]  # 1..175, no real [0,2] match anywhere
        write_floor(portal_dir, 0, [all_values])
        chunk_size = 10

        def make_session():
            initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
            return RenderSession(
                primes=initial_chunk, n=int(initial_chunk[0]), ceiling=100000, range_mode=True,
                range_primes=initial_chunk, range_step=1,
                track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
                max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
                portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
                pattern_step_mode="auto", pattern_stop_on_match=True,
                range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
            ), int(initial_chunk[0])

        bump_session, start_n = make_session()
        bump_session.bump_n(1000)
        check(bump_session._seek_thread is not None, "test setup: bump_n also moved the search to the background")
        bump_session._seek_thread.join(timeout=10)
        check(bump_session.n == start_n,
              f"bump_n leaves n unchanged once the background search confirms no match (got {bump_session.n})")

        scrub_session, start_n2 = make_session()
        scrub_session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
        scrub_session._seek_thread.join(timeout=10)
        check(scrub_session.n == start_n2, f"scrub_advance leaves n unchanged too (got {scrub_session.n})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_reset_during_flight_discards_stale_result():
    """Regression coverage for `_seek_epoch` (see reset()'s own
    doc-comment): a background pattern seek started BEFORE reset() must
    not clobber the fresh post-reset state (n=1, playback stopped,
    viz_mode back to "rings") once it finally resolves -- even though the
    search itself keeps running to completion in the background (v1 has
    no true cancellation, see _start_pattern_seek's own doc-comment), its
    result must be silently discarded."""
    from primeatlas.visualization.shared import session as session_module
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive
    import time

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        real_load_archive = session_module.load_archive
        slow_delay = 0.1

        def _slow_load_archive(*args, **kwargs):
            time.sleep(slow_delay)
            return real_load_archive(*args, **kwargs)

        session_module.load_archive = _slow_load_archive
        try:
            session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
            check(session._seek_thread is not None, "test setup: the seek is running in the background")
            in_flight_thread = session._seek_thread

            session.reset()
            check(session.n == 1 and session.range_mode is False and session.viz_mode == "rings",
                  "reset() applies its own state synchronously regardless of the in-flight seek")

            in_flight_thread.join(timeout=10)
            check(session.n == 1,
                  f"the stale seek result (the real match at {target}) is discarded, not applied on top "
                  f"of reset()'s own state (got n={session.n})")
            check(session.range_mode is False, "reset()'s own range_mode=False also survives the late finisher")
        finally:
            session_module.load_archive = real_load_archive
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_exception_clears_seek_thread_not_wedged_forever():
    """`_start_pattern_seek`'s worker must clear `_seek_thread` even when an
    exception is raised inside `_pattern_seek`'s crawl; otherwise
    `_seek_thread` stays non-None and every later tick/bump_n/scrub_advance
    call is a silent no-op in BOTH directions (the "already running" guard
    treats any non-None value the same, whether the thread is still working
    or died). Proven here by monkeypatching `_pattern_seek`
    itself to raise, then confirming (a) the thread still clears and (b)
    a SECOND, real seek afterward is not blocked by the first one's
    crash."""
    from primeatlas.visualization.shared.session import RenderSession
    import numpy as np

    range_primes = np.array([11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)
    session = RenderSession(
        primes=range_primes, n=11, ceiling=100000, range_mode=True,
        range_primes=range_primes, range_step=1,
        track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
        max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
        portal_folder="/fake/portal", viz_mode="line", pattern_offsets=[0, 2],
        pattern_step_mode="auto", pattern_stop_on_match=True,
        range_load_from=1, range_load_to=1000, chunk_size=10, sliding_enabled=False,
    )
    # sliding_enabled is False here (fake portal_folder, no real disk) --
    # flip it on by hand purely to drive _start_pattern_seek directly,
    # same trick _test_sliding_neighbor_chunk_loads_in_background_not_blocking
    # already uses.
    session.sliding_enabled = True

    real_pattern_seek = session.mode._pattern_seek

    def _raising_pattern_seek(n, is_right):
        raise RuntimeError("simulated crawl failure")

    session.mode._pattern_seek = _raising_pattern_seek
    session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(session._seek_thread is not None, "test setup: the (about-to-crash) seek is running")
    session._seek_thread.join(timeout=5)
    check(session._seek_thread is None,
          "the seek thread clears itself even when _pattern_seek raises -- navigation is not wedged")

    session.mode._pattern_seek = real_pattern_seek
    start_n = session.n
    session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    # This second seek is real and can resolve near-instantly (11,13 is
    # already a match within the already-loaded window, no chunk crossing
    # needed) -- it may already be done by the time we get back here, so
    # only join IF a thread handle is still present rather than asserting
    # one always is (that would be a race, not a real property to test).
    if session._seek_thread is not None:
        session._seek_thread.join(timeout=5)
    check(session.n != start_n or session._seek_thread is not None,
          "a SECOND, real seek is not permanently blocked by the first one's crash -- it either "
          "already resolved (n moved) or is still genuinely running")


def _test_sliding_seek_searches_with_bigger_stride_then_recenters_to_chunk_size():
    """The SEARCH crawls with the default 2 million stride while the
    RENDERING stays at the configured, possibly much smaller, chunk_size:
    a background seek should crawl with a bigger
    internal stride (fewer real chunk crossings for a sparse pattern) and
    only shrink back down to the user's own small chunk_size once a real
    match is found, so what actually gets rendered still respects that
    budget. Monkeypatches the module's own `_SEEK_STRIDE_CHUNK_SIZE`
    (real default 2,000,000 would need an impractically large synthetic
    fixture) down to 30 against the same target=359/chunk_size=10 fixture
    the plain multi-chunk seek test above already uses (6 real chunk_size=10
    crossings away) -- with stride=30, this needs far fewer real chunk
    loads to get there, and the FINAL chunk_current must still come back
    down to chunk_size=10, not stay stride-sized."""
    from primeatlas.visualization.shared import session as session_module
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        real_stride = session_module._SEEK_STRIDE_CHUNK_SIZE
        session_module._SEEK_STRIDE_CHUNK_SIZE = 30
        try:
            session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
            check(session._seek_thread is not None, "test setup: the seek is running")
            session._seek_thread.join(timeout=10)
        finally:
            session_module._SEEK_STRIDE_CHUNK_SIZE = real_stride

        check(session.n == target, f"the stride-search still reaches the correct real match (expected {target}, got {session.n})")
        check(len(session.chunk_current) <= chunk_size,
              f"chunk_current is recentered back down to the user's own chunk_size after the match "
              f"(expected <= {chunk_size}, got {len(session.chunk_current)})")
        check(int(session.chunk_current[0]) == target,
              f"chunk_current's own first element is still the matched value after recentering "
              f"(got {int(session.chunk_current[0]) if len(session.chunk_current) else None})")
        check(target in session.mode._pattern_primes_set and (target + 2) in session.mode._pattern_primes_set,
              "the matched pair is present in the rebuilt _pattern_primes_set after recentering")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_fast_in_chunk_match_skips_recenter():
    """When a match is found entirely within the already-loaded
    chunk_current (no chunk crossing needed at all), `_effective_chunk_size`
    is never even called -- `_seek_used_stride` stays False, so
    `_recenter_render_chunks` is skipped and chunk_current is exactly
    whatever it already was, not needlessly reloaded."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = sieve_primes_upto(200)
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 100
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)

        session = RenderSession(
            primes=initial_chunk, n=int(initial_chunk[0]), ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        chunk_current_before = session.chunk_current

        session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
        # An in-chunk match can resolve near-instantly (no real I/O at
        # all) -- the thread may already be done by the time we get back
        # here, so only join IF a handle is still present (same race
        # avoidance as the exception-safety test's own "second seek" check).
        if session._seek_thread is not None:
            session._seek_thread.join(timeout=10)

        check(session.chunk_current is chunk_current_before,
              "an in-chunk match (no slide needed) never reloads chunk_current at all -- "
              "_recenter_render_chunks is skipped since the stride was never actually used")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    _test_sliding_seek_runs_in_background_not_blocking_main_thread()
    _test_sliding_seek_ignores_further_nav_input_while_in_flight()
    _test_sliding_seek_hud_shows_searching_while_in_flight()
    _test_sliding_seek_tick_not_found_stops_playback_in_background()
    _test_sliding_seek_bump_and_scrub_not_found_leave_n_unchanged_async()
    _test_sliding_seek_reset_during_flight_discards_stale_result()
    _test_sliding_seek_exception_clears_seek_thread_not_wedged_forever()
    _test_sliding_seek_searches_with_bigger_stride_then_recenters_to_chunk_size()
    _test_sliding_seek_fast_in_chunk_match_skips_recenter()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
