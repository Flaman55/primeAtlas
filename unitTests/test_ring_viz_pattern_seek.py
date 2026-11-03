"""
test_ring_viz_pattern_seek.py -- RenderSession's pattern step mode and seek
(session.py): stop-on-match, no artificial step cap, staying on the last real match at
a genuine window edge, and the sliding range window that loads neighbor chunks while
seeking forward and backward, including its edge-reached messages (console and HUD).
The seek running on a background thread is in test_ring_viz_pattern_seek_async.py.

No moderngl/glfw import anywhere -- same "pure logic, GPU-free" convention as every
other ring_viz test in this folder.

Usage: python unitTests\\test_ring_viz_pattern_seek.py
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


def _test_pattern_step_mode_and_stop_on_match():
    """Manual/Auto radio (`pattern_step_mode`) plus a "MATCH!" checkbox
    (`pattern_stop_on_match`) -- "manual" ALWAYS takes a single wheel step,
    showing every candidate whether it's a match or not, regardless of the
    checkbox; "auto" ALWAYS seeks -- for the next real MATCH! when checked, or
    specifically for the next NON-match when unchecked (skipping real matches
    on the way, e.g. 97 here). k=6 offsets [0,4,6,10,12,16] seeded at p0=7
    (sequence 7 -> 97 -> 1357: 7 and 97 are real matches, 1357 isn't),
    verified against a real sieve rather than re-asserting whatever
    _pattern_seek itself would compute."""
    from primeatlas.visualization.shared.session import RenderSession
    import numpy as np

    range_primes = np.array(sieve_primes_upto(1400), dtype=np.int64)

    def make_session(step_mode, stop_on_match):
        return RenderSession(
            primes=range_primes, n=7, ceiling=10000, range_mode=True,
            range_primes=range_primes, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
            portal_folder=None, viz_mode="line", pattern_offsets=[0, 4, 6, 10, 12, 16],
            pattern_step_mode=step_mode, pattern_stop_on_match=stop_on_match,
        )

    manual_off = make_session("manual", False)
    check(manual_off.mode._pattern_uses_seek() is False, "manual mode never seeks, regardless of the checkbox")
    manual_off.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(manual_off.n == 97, f"manual + unchecked takes a single wheel step, 7 -> 97 (got {manual_off.n})")

    manual_on = make_session("manual", True)
    check(manual_on.mode._pattern_uses_seek() is False,
          "manual mode ALSO never seeks with the checkbox CHECKED -- the radio is the master switch")
    manual_on.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(manual_on.n == 97, f"manual + checked still takes a single wheel step, 7 -> 97 (got {manual_on.n})")

    auto_on = make_session("auto", True)
    check(auto_on.mode._pattern_uses_seek() is True, "auto mode always seeks")
    auto_on.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(auto_on.n == 97, f"auto + checked seeks the next real MATCH!, which is 97 -- the very first "
                           f"wheel candidate already qualifies (got {auto_on.n})")

    auto_off = make_session("auto", False)
    check(auto_off.mode._pattern_uses_seek() is True, "auto mode always seeks, checkbox unchecked too")
    auto_off.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(auto_off.n == 1357,
          f"auto + unchecked seeks the next NON-match, skipping straight OVER the real match at 97 "
          f"(a wheel candidate, but not what was asked for) to land on 1357 (got {auto_off.n})")

    # tick() and bump_n must agree with scrub_advance on the same regime.
    auto_off_tick = make_session("auto", False)
    auto_off_tick.playback_running = True
    stopped = auto_off_tick.tick()
    check(stopped is False, "tick() in seek-non-match mode doesn't stop playback just because it skipped a match")
    check(auto_off_tick.n == 1357, f"tick() in seek-non-match mode also skips 97, landing on 1357 (got {auto_off_tick.n})")

    auto_off_bump = make_session("auto", False)
    auto_off_bump.bump_n(1000)
    check(auto_off_bump.n == 1357,
          f"bump_n in seek-non-match mode also skips 97, ignoring its own delta magnitude (got {auto_off_bump.n})")


def _test_pattern_seek_has_no_artificial_step_cap():
    """--pattern-stop-on-match's seek has NO step cap: at archive scale a
    match can legitimately need more than any fixed number of wheel-hops
    (e.g. 50,000), and a capped seek would either land on a bare non-match
    wheel candidate or freeze playback/scrub once the budget is exhausted. At
    each stop the seek checks whether the candidate is a match and whether
    MATCH! is checked, and keeps going otherwise; it terminates only on
    finding the desired kind or on _pattern_wheel_step reporting the genuine
    window edge (see _pattern_seek's doc-comment for why that always
    terminates).

    Proves the "many steps before a real match" half of this directly: a
    real match is manually placed 500 wheel-hops from the anchor in an
    otherwise permanently-synthetic-non-matching loaded range, and the seek
    must still reach it."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.rings.line.line_geometry import pattern_positions_and_match
    import numpy as np

    base_values = [6 * k + 1 for k in range(1, 20000)]  # only == 1 mod 6 -- never a match on its own

    def make_session(extra_values=()):
        values = sorted(set(base_values) | set(extra_values))
        range_primes = np.array(values, dtype=np.int64)
        session = RenderSession(
            primes=range_primes, n=11, ceiling=1_000_000, range_mode=True,
            range_primes=range_primes, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
            portal_folder=None, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
        )
        return session, range_primes

    # Walk 500 real wheel-hops forward from the anchor via plain single steps
    # (bypassing _pattern_seek itself) to find a concrete, deep candidate.
    probe_session, _ = make_session()
    target = 11
    for _ in range(500):
        target = probe_session.mode._pattern_wheel_step(target, True)
    check(target != 11, "test setup: 500 wheel-hops actually moved somewhere")

    matched_session, range_primes = make_session(extra_values=(target, target + 2))
    _positions, _hits, all_match = pattern_positions_and_match(
        target, [0, 2], set(int(v) for v in range_primes))
    check(all_match is True, "test setup: the manually-inserted pair really is a match")

    matched_session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(matched_session.n == target,
          f"_pattern_seek reaches a real match 500 wheel-hops away instead of giving up early "
          f"(expected {target}, got {matched_session.n})")


def _test_pattern_seek_stays_on_last_real_match_at_genuine_window_edge():
    """Companion to the "no artificial cap" test above: if the next step is
    not a match and there's no further one because the range ended, `n` stays
    on the last CORRECT one. tick()/bump_n/scrub_advance must not apply
    _pattern_seek's `new_n` when it returned found=False (that would land on
    the last non-match wheel candidate reached on the way to the edge); `n`
    stays exactly where it was (the last confirmed MATCH!) when the seek can't
    find another one before running out of loaded window.

    Built with the same "only == 1 mod 6" synthetic base as the no-cap
    test (guarantees zero INCIDENTAL matches), plus exactly ONE real match
    manually inserted at the anchor itself (n=11, by adding 11 to the set
    -- its partner 13 == 1 mod 6 is already there) -- so there is a real
    "last correct" position to stay on, and definitively no further one
    anywhere ahead of it in this tiny window."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.rings.line.line_geometry import pattern_positions_and_match
    import numpy as np

    values = sorted(set(6 * k + 1 for k in range(1, 200)) | {11})  # tiny window, one real match at 11
    range_primes = np.array(values, dtype=np.int64)

    def make_session():
        return RenderSession(
            primes=range_primes, n=11, ceiling=100000, range_mode=True,
            range_primes=range_primes, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
            portal_folder=None, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
        )

    _positions, _hits, all_match = pattern_positions_and_match(
        11, [0, 2], set(int(v) for v in range_primes))
    check(all_match is True, "test setup: n=11 really is a genuine match")

    seek_session = make_session()
    _final_n, found = seek_session.mode._pattern_seek(11, True)
    check(found is False, "no FURTHER real match exists ahead of 11 in this tiny window")

    tick_session = make_session()
    tick_session.playback_running = True
    stopped = tick_session.tick()
    check(stopped is True, "tick() stops immediately rather than advancing to a non-match candidate")
    check(tick_session.n == 11, f"tick() leaves n on the last real match (11), not a non-match candidate "
                                f"further along (got {tick_session.n})")

    bump_session = make_session()
    bump_session.bump_n(1000)
    check(bump_session.n == 11, f"bump_n leaves n on the last real match too (got {bump_session.n})")

    scrub_session = make_session()
    scrub_session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(scrub_session.n == 11, f"scrub_advance leaves n on the last real match too (got {scrub_session.n})")


def _test_sliding_forward_multi_chunk_seek_finds_distant_match():
    """A --load-range covering nearly a whole floor must be reachable beyond
    the first --max-load-count primes: a seek crosses MULTIPLE chunk
    boundaries in a single call (swapping mid-loop) and lands on a real match
    several chunks past the initially-loaded one, instead of stopping at the
    loaded buffer's edge.

    Data: 70 values of the form 6k+1 (k=0..69, i.e. 1..415) -- by
    construction no two of these are ever 2 apart, so (same convention as
    the no-artificial-cap test above) every wheel-compatible candidate
    fails the [0,2] match check until it reaches a manually-inserted real
    pair. That pair (359, 361) is placed so it lands as chunk index 6's own
    FIRST element once split into chunk_size=10 chunks -- reaching it from the
    initial chunk (chunk 0) requires 6 real forward slides."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        check(all_values[60] == target,
              f"test setup: target lands exactly at chunk index 6's own first element "
              f"(got index of {target}: {all_values.index(target)})")
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        check(len(initial_chunk) == chunk_size, "test setup: the initial chunk loaded exactly chunk_size values")

        session = RenderSession(
            primes=initial_chunk, n=1, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        check(session.sliding_enabled is True, "sliding_enabled turns on when every required kwarg is given")
        check(session.chunk_back is not None and len(session.chunk_back) == 0,
              "chunk_back is confirmed empty (not None/unattempted) at the true start of range_load_from")
        check(session.chunk_forward is not None and len(session.chunk_forward) > 0,
              "chunk_forward is EAGERLY preloaded at construction, not left as None until first needed")

        session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
        # With sliding enabled, a multi-chunk seek now runs on a background
        # thread (see _start_pattern_seek's doc-comment) instead of blocking this
        # call -- join it before
        # asserting the outcome, same as a real caller waits via the main
        # loop's own n_force_rebuild-triggered rebuild.
        check(session._seek_thread is not None, "test setup: the seek actually moved to a background thread")
        session._seek_thread.join(timeout=5)
        check(session._seek_thread is None, "the seek thread clears itself once the search resolves")
        check(session.n == target,
              f"a single scrub_advance call crosses multiple chunk boundaries and reaches a real "
              f"match several chunks away (expected {target}, got {session.n})")
        check(int(session.chunk_current[0]) == target,
              f"chunk_current itself has slid forward so the found match is its own first element "
              f"(got chunk_current[0]={int(session.chunk_current[0]) if len(session.chunk_current) else None})")
        check(target in session.mode._pattern_primes_set and (target + 2) in session.mode._pattern_primes_set,
              "the matched pair is present in the rebuilt _pattern_primes_set after sliding")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_backward_swap_mirror():
    """Mirror of the forward slide: _slide_backward swaps chunk_current
    into chunk_forward, promotes chunk_back into chunk_current, and reloads
    a fresh chunk_back via load_archive_before -- called directly (not via
    a full wheel-seek) since the forward test above already proves the
    higher-level integration; this pins the backward primitive itself."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 40)]  # 1..235, no real [0,2] matches anywhere
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        # Start on the SECOND chunk (values[10:20]) so there's real data
        # both behind and ahead of the initial window.
        second_chunk = load_archive(portal_dir, upto=1000, from_n=all_values[9], max_load_count=chunk_size)
        check(list(second_chunk) == all_values[10:20], "test setup: second_chunk is exactly values[10:20]")

        session = RenderSession(
            primes=second_chunk, n=int(second_chunk[0]), ceiling=100000, range_mode=True,
            range_primes=second_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=False,
            # range_load_from=0, not 1: `not_below` is EXCLUSIVE (mirrors
            # load_archive's own `from_n` convention) -- 0 sits safely below
            # every real all_values entry (which start at 1) so it never
            # collides with a real loaded value the way range_load_from=1
            # would (all_values[0] is exactly 1).
            range_load_from=0, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        check(list(session.chunk_current) == all_values[10:20], "chunk_current starts as the second chunk")
        check(list(session.chunk_back) == all_values[0:10],
              f"chunk_back is eagerly preloaded as the FIRST chunk at construction "
              f"(got {list(session.chunk_back)!r})")
        check(list(session.chunk_forward) == all_values[20:30],
              f"chunk_forward is eagerly preloaded as the third chunk at construction "
              f"(got {list(session.chunk_forward)!r})")

        slid = session._slide_backward()
        check(slid is True, "_slide_backward reports success when a real back chunk was available")
        check(list(session.chunk_current) == all_values[0:10],
              "chunk_back was promoted into chunk_current")
        check(list(session.chunk_forward) == all_values[10:20],
              "the old chunk_current was demoted into chunk_forward (swap, not reload)")
        # The fresh chunk_back kicked off right after the swap runs in the
        # BACKGROUND (see _ensure_back_chunk's own doc-comment) -- _slide_
        # backward itself doesn't wait for it, by design, so explicitly
        # wait here before checking its final contents (mirrors how a
        # REAL caller eventually resolves it via another _slide_backward/
        # _wait_for_back_chunk call).
        session._wait_for_back_chunk()
        check(session.chunk_back is not None and len(session.chunk_back) == 0,
              "a fresh chunk_back was loaded right after the swap and correctly found the true "
              "start of range_load_from (nothing before value 1)")

        slid_again = session._slide_backward()
        check(slid_again is False,
              "a further _slide_backward at the true start of range_load_from correctly reports no-op")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_neighbor_chunk_loads_in_background_not_blocking():
    """_ensure_forward_chunk/_ensure_back_chunk load the neighbor chunk on a
    background daemon thread: the renderer's GLFW loop is single-threaded, so
    a synchronous load_archive/load_archive_before call would block the
    entire window for the whole disk read on EVERY swap, even though the swap
    itself uses already-ready data.

    Proves the actual async contract directly (not just that the final
    DATA ends up correct, which the other sliding tests above already
    cover): monkeypatches session.load_archive with an artificially slow
    stand-in, and checks that _ensure_forward_chunk returns almost
    instantly regardless (the whole point), that chunk_forward is
    genuinely still None with a real thread running immediately
    afterward (not silently already finished), and that
    _wait_for_forward_chunk both waits for and returns the real result."""
    from primeatlas.visualization.shared import session as session_module
    from primeatlas.visualization.shared.session import RenderSession
    import numpy as np
    import time

    range_primes = np.array([11, 13, 17, 19, 23], dtype=np.int64)
    session = RenderSession(
        primes=range_primes, n=11, ceiling=100000, range_mode=True,
        range_primes=range_primes, range_step=1,
        track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
        max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
        portal_folder="/fake/portal", viz_mode="line", pattern_offsets=[0, 2],
        pattern_step_mode="auto", pattern_stop_on_match=True,
        range_load_from=1, range_load_to=1000, chunk_size=10, sliding_enabled=False,
    )
    # sliding_enabled is False here (portal_folder is fake, no real disk to
    # read) -- flip it on by hand purely to drive _ensure_forward_chunk
    # directly without needing a real portal on disk for this specific test.
    session.sliding_enabled = True

    real_load_archive = session_module.load_archive
    slow_load_delay = 0.3

    def _slow_load_archive(*args, **kwargs):
        time.sleep(slow_load_delay)
        return np.array([29, 31, 37], dtype=np.uint64)

    session_module.load_archive = _slow_load_archive
    try:
        t0 = time.perf_counter()
        session._ensure_forward_chunk()
        elapsed = time.perf_counter() - t0
        check(elapsed < slow_load_delay / 2,
              f"_ensure_forward_chunk returns almost instantly, NOT blocking for the load's own "
              f"{slow_load_delay}s duration (got {elapsed:.3f}s)")
        check(session.chunk_forward is None,
              "chunk_forward is genuinely still None right after kickoff -- the slow load hasn't "
              "actually finished yet, this isn't a race that happened to complete instantly")
        check(session._forward_load_thread is not None,
              "a real background thread handle is set while the load is in flight")

        session._wait_for_forward_chunk()
        check(list(session.chunk_forward) == [29, 31, 37],
              f"_wait_for_forward_chunk blocks until the background load actually finishes and "
              f"the real result is available (got {list(session.chunk_forward) if session.chunk_forward is not None else None!r})")
        check(session._forward_load_thread is None,
              "the thread handle is cleared again once the load completes")
    finally:
        session_module.load_archive = real_load_archive


def _test_sliding_disabled_by_default_without_full_wiring():
    """sliding_enabled must degrade gracefully to False (a fixed slice)
    whenever the caller passes sliding_enabled=True but omits any of the
    OTHER kwargs needed to do it safely (portal_folder, chunk_size,
    range_load_to) -- e.g. the GUI and CLI sides wired inconsistently.
    Constructing RenderSession without ANY of these kwargs is covered by the
    other tests in this file."""
    from primeatlas.visualization.shared.session import RenderSession
    import numpy as np

    range_primes = np.array([11, 13, 17, 19, 23], dtype=np.int64)

    def make(**kwargs):
        return RenderSession(
            primes=range_primes, n=11, ceiling=100000, range_mode=True,
            range_primes=range_primes, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
            portal_folder=None, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            sliding_enabled=True, **kwargs,
        )

    check(make().sliding_enabled is False, "sliding_enabled=True alone (no portal_folder/chunk_size/range_load_to) still degrades to False")
    check(make(chunk_size=10).sliding_enabled is False, "still False without a real range_load_to")
    check(make(chunk_size=10, range_load_to=1000).sliding_enabled is False,
          "still False without a real portal_folder (portal_folder=None here)")


def _test_sliding_found_false_means_true_range_edge_not_chunk_edge():
    """Core correctness requirement: once sliding is enabled,
    `found=False` from tick()/_pattern_seek must mean the TRUE
    range_load_to edge was reached (chunk_forward genuinely empty), not
    merely the INITIALLY loaded chunk's own edge -- the whole point of this
    feature. Uses a small range_load_to so the true edge is reachable
    quickly: no real [0,2] match exists anywhere in this data (same 6k+1
    trick), so the seek must slide all the way to the actual end of
    range_load_to and only THEN report found=False/stop, proving it didn't
    stop early at chunk 0's own boundary."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 30)]  # 1..175, no real [0,2] match anywhere
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)

        session = RenderSession(
            primes=initial_chunk, n=1, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        playback_session_ceiling_before_slide = int(session.chunk_current[-1])

        final_n, found = session.mode._pattern_seek(1, True)
        check(found is False, "no real match exists anywhere in range_load_from..range_load_to")
        check(int(session.chunk_current[-1]) > playback_session_ceiling_before_slide,
              f"the search actually SLID forward past the initial chunk's own edge before giving up "
              f"(initial edge={playback_session_ceiling_before_slide}, "
              f"final chunk_current[-1]={int(session.chunk_current[-1])})")
        check(session.chunk_forward is not None and len(session.chunk_forward) == 0,
              "gives up only once chunk_forward is confirmed genuinely empty -- the TRUE range_load_to "
              "edge, not just wherever the initially-loaded chunk happened to end")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_forward_respects_range_load_to_hard_boundary():
    """Symmetric counterpart to the backward not_below test: the TO value is
    a hard boundary too, so sliding never goes further than the set range.
    Forward sliding reuses load_archive(upto=range_load_to), which always
    hard-bounds by `upto` (`arr <= upto`, plus a floor-level `floor_lo >
    upto: break`); this test proves that at the RenderSession/sliding level
    with the same rigor as the backward test: floor 1 holds real data FAR
    beyond range_load_to, and sliding forward must never reach it."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        floor0_values = [6 * k + 1 for k in range(0, 30)]  # 1..175
        write_floor(portal_dir, 0, [floor0_values])
        write_floor(portal_dir, 1, [[181, 187, 193, 199, 211]])  # real data well past range_load_to

        chunk_size = 5
        range_load_to = 49  # strictly inside floor 0's own span
        initial_chunk = load_archive(portal_dir, upto=range_load_to, max_load_count=chunk_size)
        check(list(initial_chunk) == floor0_values[:5],
              f"test setup: the initial chunk is the first 5 values (got {list(initial_chunk)!r})")

        session = RenderSession(
            primes=initial_chunk, n=1, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=0, range_load_to=range_load_to, chunk_size=chunk_size, sliding_enabled=True,
        )
        # Slide forward as many times as it'll allow -- must stop cleanly,
        # never returning a chunk containing anything > range_load_to, and
        # NEVER anything from floor 1 (181+) leaking in no matter how many
        # times we try.
        for _ in range(10):
            session._slide_forward()
        check(all(int(v) <= range_load_to for v in session.chunk_current),
              f"chunk_current never holds a value past range_load_to={range_load_to} "
              f"(got {list(session.chunk_current)!r})")
        check(all(int(v) < 181 for v in session.chunk_current),
              "not a single floor-1 value (>=181) ever leaked into chunk_current")
        check(session.chunk_forward is not None and len(session.chunk_forward) == 0,
              "chunk_forward is confirmed genuinely empty at the true range_load_to edge")

        final_n, found = session.mode._pattern_seek(1, True)
        check(found is False, "no real match exists in this synthetic data")
        check(all(int(v) <= range_load_to for v in session.chunk_current),
              "a full seek to the genuine forward edge still never exceeds range_load_to")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_edge_reached_prints_explicit_message():
    """Explicit information when a move is refused because it would exceed
    FROM or TO.
    Console-output test (this module's own convention elsewhere, e.g.
    HUD/rebuild lines, already prints rather than returning strings) --
    captures stdout around a call that's already AT the genuine edge in
    each direction and checks the exact boundary value appears."""
    import contextlib
    import io
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 10)]  # 1..55
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 100  # bigger than the whole dataset -- one chunk covers everything
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)

        session = RenderSession(
            primes=initial_chunk, n=1, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=0, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            slid_fwd = session._slide_forward()
            slid_fwd_again = session._slide_forward()
        check(slid_fwd is False and slid_fwd_again is False, "test setup: already at the true forward edge")
        out = buf.getvalue()
        check("TO edge" in out and "1,000" in out,
              f"the forward edge message names the real TO value (got {out!r})")
        check(out.count("TO edge") == 1,
              f"the message is printed exactly ONCE, not once per repeated call at the same edge "
              f"(deduped) (got {out.count('TO edge')} times in {out!r})")

        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            slid_back = session._slide_backward()
            slid_back_again = session._slide_backward()
        check(slid_back is False and slid_back_again is False, "test setup: already at the true backward edge")
        out2 = buf2.getvalue()
        check("FROM edge" in out2 and "(0)" in out2,
              f"the backward edge message names the real FROM value (got {out2!r})")
        check(out2.count("FROM edge") == 1,
              f"the backward message is also deduped to exactly once (got {out2.count('FROM edge')} "
              f"times in {out2!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_edge_reached_shows_in_hud_not_just_console():
    """The edge message must also appear in the GL window's HUD, not only on
    the console. N
    staying unchanged at a genuine edge means renderer.py's own main-loop
    rebuild gate (`session.n != last_n`) never fires by itself, so without
    `n_force_rebuild` being set, rebuild_line (the only place that
    refreshes `hud_lines`) would never even run. Proves both halves:
    n_force_rebuild becomes True, and calling rebuild_line (as the main
    loop would) actually surfaces an edge line in hud_lines."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        # 12 values, chunk_size=3: enough room for a REAL forward slide to
        # actually swap (not just hit its own edge too) -- needed so the
        # test's own final "moved away, HUD line disappears" check
        # exercises a genuine swap, not another edge-hit.
        all_values = [6 * k + 1 for k in range(0, 12)]  # 1..67
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 3
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        check(list(initial_chunk) == all_values[:3], "test setup: initial chunk is the first 3 values")

        session = RenderSession(
            primes=initial_chunk, n=1, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=0, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        session.n_force_rebuild = False  # construction may have left leftover state -- start clean

        session._slide_backward()
        check(session.n_force_rebuild is True,
              "n_force_rebuild is set the first time a genuine edge is newly reached, so "
              "renderer.py's own main loop refreshes the HUD even though N itself didn't move")

        session.rebuild(session.n)
        check(any("FROM edge" in line for line in session.hud_lines),
              f"rebuild_line's own hud_lines includes the FROM-edge indicator once the flag "
              f"is set, not just the console print (got {session.hud_lines!r})")

        # Sliding away from the edge clears both the flag and, on the NEXT
        # rebuild, the HUD line -- it must not linger forever once the
        # user has moved on.
        session._slide_forward()
        session.rebuild(session.n)
        check(not any("FROM edge" in line for line in session.hud_lines),
              f"the edge HUD line disappears again once the session has moved away from it "
              f"(got {session.hud_lines!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_edge_message_clears_on_in_chunk_step_no_slide_needed():
    """After a step in the OPPOSITE direction from an edge, the edge message
    must disappear -- including a step that stays within the ALREADY-loaded
    chunk_current (no chunk crossing, the common case for a small step right
    after bouncing off an edge), which never calls _slide_forward/
    _slide_backward.

    Forces a small, dense wheel (modulus=6, residues=[1]) directly onto a
    real session so multiple wheel-compatible positions exist WITHIN one
    small chunk -- proving the fix covers the in-chunk case specifically,
    not just a chunk-crossing move (the OTHER sliding tests above already
    cover that half)."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 12)]  # 1..67, all ≡1 mod 6
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 3
        initial_chunk = load_archive(portal_dir, upto=1000, from_n=all_values[2], max_load_count=chunk_size)
        check(list(initial_chunk) == all_values[3:6], "test setup: initial chunk is values[3:6] ([19,25,31])")

        session = RenderSession(
            primes=initial_chunk, n=int(initial_chunk[0]), ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=False,
            range_load_from=0, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        # Force a small, dense wheel so a step within a single chunk (no
        # slide) is actually possible -- every all_values entry (all ≡1
        # mod 6) is itself wheel-compatible under this forced wheel.
        session.mode.pattern_wheel_modulus = 6
        session.mode.pattern_wheel_residues = [1]

        # Reach the TRUE FROM edge: first slide is a real chunk crossing
        # (values[0:3]=[1,7,13] is real data), second slide hits the
        # genuine start.
        session._slide_backward()
        check(session._back_edge_reported is False, "test setup: one real back chunk still remained")
        session._slide_backward()
        check(session._back_edge_reported is True, "test setup: now genuinely at the true FROM edge")
        check(list(session.chunk_current) == [1, 7, 13], "test setup: chunk_current is now the true-first chunk")
        session.n = int(session.chunk_current[0])  # keep n in sync -- _slide_backward itself never touches it

        # One step FORWARD, opposite direction -- with chunk_current
        # holding THREE wheel-compatible entries, this must resolve
        # entirely WITHIN it, no slide needed at all.
        new_n = session.mode._pattern_wheel_step(session.n, True)
        check(new_n == 7, f"the forward step found the next in-chunk candidate, no slide needed (got {new_n})")
        check(list(session.chunk_current) == [1, 7, 13],
              "sanity: chunk_current itself did NOT change -- this really was an in-chunk step")
        check(session._back_edge_reported is False,
              "the stale FROM-edge flag is cleared by an in-chunk step too, not just a real slide")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_to_edge_message_clears_on_in_chunk_step_no_slide_needed():
    """Symmetric counterpart to the FROM-edge in-chunk test above -- same
    behavior
    (_pattern_wheel_step clears BOTH edge flags on any genuine move,
    regardless of direction), same in-chunk-step scenario, mirrored for
    the TO/forward edge instead."""
    from primeatlas.visualization.shared.session import RenderSession
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 12)]  # 1..67, all ≡1 mod 6
        write_floor(portal_dir, 0, [all_values])

        chunk_size = 3
        range_load_to = 45  # strictly between values[6]=37 and values[7]=43 -- true forward edge inside floor 0
        initial_chunk = load_archive(portal_dir, upto=range_load_to, from_n=all_values[2], max_load_count=chunk_size)
        check(list(initial_chunk) == all_values[3:6], "test setup: initial chunk is values[3:6] ([19,25,31])")

        session = RenderSession(
            primes=initial_chunk, n=int(initial_chunk[0]), ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=False,
            range_load_from=0, range_load_to=range_load_to, chunk_size=chunk_size, sliding_enabled=True,
        )
        session.mode.pattern_wheel_modulus = 6
        session.mode.pattern_wheel_residues = [1]

        # Reach the TRUE TO edge: first slide is real (values[6:9] =
        # [37,43], both <= range_load_to=45), second slide hits the
        # genuine end (nothing left <= 45 past that).
        session._slide_forward()
        check(session._forward_edge_reported is False, "test setup: one real forward chunk still remained")
        session._slide_forward()
        check(session._forward_edge_reported is True, "test setup: now genuinely at the true TO edge")
        check(list(session.chunk_current) == [37, 43], "test setup: chunk_current is now the true-last chunk")
        session.n = int(session.chunk_current[-1])  # keep n in sync -- _slide_forward itself never touches it

        # One step BACKWARD, opposite direction -- chunk_current holds TWO
        # wheel-compatible entries, so this resolves entirely within it.
        new_n = session.mode._pattern_wheel_step(session.n, False)
        check(new_n == 37, f"the backward step found the next in-chunk candidate, no slide needed (got {new_n})")
        check(list(session.chunk_current) == [37, 43],
              "sanity: chunk_current itself did NOT change -- this really was an in-chunk step")
        check(session._forward_edge_reported is False,
              "the stale TO-edge flag is cleared by an in-chunk step too, not just a real slide")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    _test_pattern_step_mode_and_stop_on_match()
    _test_pattern_seek_has_no_artificial_step_cap()
    _test_pattern_seek_stays_on_last_real_match_at_genuine_window_edge()
    _test_sliding_forward_multi_chunk_seek_finds_distant_match()
    _test_sliding_backward_swap_mirror()
    _test_sliding_neighbor_chunk_loads_in_background_not_blocking()
    _test_sliding_disabled_by_default_without_full_wiring()
    _test_sliding_found_false_means_true_range_edge_not_chunk_edge()
    _test_sliding_forward_respects_range_load_to_hard_boundary()
    _test_sliding_edge_reached_prints_explicit_message()
    _test_sliding_edge_reached_shows_in_hud_not_just_console()
    _test_sliding_edge_message_clears_on_in_chunk_step_no_slide_needed()
    _test_sliding_to_edge_message_clears_on_in_chunk_step_no_slide_needed()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
