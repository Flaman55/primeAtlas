# Ring visualization tab -- implementation plan

Branch: `ring-visualization` (off `main`, created 2026-09-04).

## Goal

Bring Structural Sieve's "drum" visualization (rings + hit teeth -- see
`js/render/DrumRenderer.js` and `js/core/SieveModel.js` in the
RelationalMathematics repo) into PrimeAtlas as a real tab, backed by the
magazyn's own prime storage and rendered on the GPU, at a ring count no
browser tab could reach.

## Feasibility already confirmed (2026-09-04, before this plan was written)

A standalone prototype was built and run on Artur's real hardware before
committing to this plan, specifically to avoid designing a full tab around an
unproven rendering approach:

- `ring_geometry.py` -- pure-numpy port of the JS ring/window math
  (radius/phase/angle, Bertrand/Legendre/General Law window bounds). 27/27
  unit tests passing (`test_ring_geometry.py`), including the same
  invariants already validated in the JS reference (theta=0.5 reproduces
  Legendre exactly, General Law width never exceeds Legendre's, the
  N=9/15/16 perfect-square level edge case, etc.). Benchmarked at ~20M
  rings/second on plain CPU numpy in the sandbox that built it.
- `structural_rings_poc.py` -- moderngl + glfw renderer, `GL_POINTS` with a
  soft-circle fragment shader, pan/zoom as a GPU-side camera transform
  (never touches the CPU-side ring buffer), ring buffer rebuilt only on an
  N-change.
- **Real-hardware result (Artur, 2026-09-04):** 20,000,000 rings loaded in
  0.27s, N-change rebuild ~1.3s, pan/zoom stayed at 50+ fps even with a fast
  scroll wheel (Logitech MX Anywhere 3S) at the full 20M-ring view. This is
  the number that justifies building a real tab around this approach rather
  than treating it as a curiosity.

This plan assumes that result and does not re-litigate the rendering
approach; it only sequences turning the proven prototype into a maintained
part of the app.

## Open design decisions (settle these before/at the start of Faza 0-3, not
mid-implementation)

1. **Window embedding.** The prototype opens its own native `glfw` window.
   Embedding an OpenGL canvas inside a Tkinter widget was NOT attempted --
   GL's own event loop does not compose cleanly with Tkinter's `mainloop()`,
   and nothing elsewhere in this codebase embeds GL inside Tk. Default plan:
   launch the renderer as a **separate process** from a button in the new
   tab, the same way the Generation tab already launches long-running WSL
   scripts (`GenerationConsole`/`WslLoggedRunner`) -- proven pattern, no new
   process-management code needed. Revisit only if Artur specifically wants
   it inside the main window.
2. **Data source at real magazyn scale.** The prototype's `load_magazyn()`
   walks floors sequentially with no chunking -- fine for the scales tested
   so far, but this project has already hit exactly this class of problem
   before (`04_C_skaner musi czytać pliki magazynu w porcjach` -- see
   project memory) once a floor span gets large. Faza 2 below hardens this
   before it becomes a silent failure at whatever N Artur first tries for
   real.
3. **Visual parity with the browser version.** The prototype only draws two
   colors (cyan / gold-on-hit) -- none of DrumRenderer's Bertrand/Legendre/
   General Law highlight colors, tracked-ring outlines, resonance flashes,
   or HUD text exist yet. `ring_geometry.py` already has the pure Bertrand/
   Legendre/General-Law membership math ported (Faza 0 landed it), so this
   is a rendering-layer addition, not new math -- sequenced as Faza 1/4
   below so the tab is useful (raw ring field) well before it's feature-
   complete.
4. **N navigation.** Prototype: arrow keys only (step / 100x page-jump).
   Production tab should let a user jump to a specific N from a text field,
   reusing the existing "search a specific number" UX already in the Primes
   tab (`storage.find_prime_in_floor`) rather than inventing a second
   search box with different conventions.
5. **Process lifecycle.** The renderer subprocess needs to start/stop
   cleanly with the tab (opened on demand, killed on tab close or app
   quit) -- reuse the existing WSL subprocess-management class rather than
   writing new lifecycle code for this one feature.

## Phased implementation

Mirrors this project's own Faza-by-Faza convention (see README.md's history
of every other multi-step feature) -- each phase should be its own
reviewable chunk, verified before the next starts.

**Faza 0 -- Land the proven artifacts, verify nothing broke**
- Copy `ring_geometry.py` + `test_ring_geometry.py` into `primeatlas/`
  (pure logic, no tkinter dependency -- same convention `storage.py`'s own
  docstring already documents for this package).
- Copy `structural_rings_poc.py` in as the reference renderer (exact
  in-repo location TBD -- proposal: `primeatlas/ring_viz/renderer.py`).
- Run the full existing `unitTests/` suite + the new ring tests together,
  confirm no collisions/regressions.

**Faza 1 -- Full highlight-math parity in `ring_geometry.py`**
- Port `StructuralSieveApp.js`'s `#computeHighlightColor` /
  `#windowHighlightFamilies` additive-blend logic (Bertrand pink, Legendre
  green, General Law violet, blended when more than one window is active).
- Port `SieveModel.resonanceEventsInRange` for the resonance-flash trigger.
- Extend `test_ring_geometry.py` to cover both, mirroring the JS test
  suite's own coverage of the same logic.

**Faza 2 -- Harden the magazyn data source**
- Replace the prototype's naive per-floor loop with one built on
  `storage.list_pietra` / `list_source_filenames` properly, reading in
  bounded chunks (not one unbounded pass across every floor up to N), with
  progress reporting back to the tab.
- Decide and document the real ceiling: at what N does "read primes for the
  ring buffer" itself become the bottleneck, separate from the already-
  proven rendering ceiling.

**Faza 3 -- The actual tab**
- New `primeatlas/rings_tab.py` (`RingsTab(BaseTab)`), same construction
  pattern as every other `*_tab.py`.
- UI: floor/N picker (reusing the existing search-box conventions),
  "Otwórz wizualizację" button.
- Launches the Faza 0 renderer as a subprocess parametrized by the chosen
  portal folder + N, using the existing WSL/GenerationConsole subprocess
  pattern for start/stop/status instead of new lifecycle code.
- PL/EN locale keys.

**Faza 4 -- HUD + visual polish**
- Surface DrumRenderer's HUD fields (counter, window range text, factors of
  N, LCM lines) -- either drawn directly in the GL window or in a small
  Tkinter side panel reading a status file the subprocess writes each
  frame/tick (decide which once Faza 3's process-boundary is real).
- Color/glow parity pass against the browser version.

**Faza 5 -- Verification + commit**
- Full regression (existing suite + new tests), manual smoke test on
  Artur's real hardware at the scales already proven (20M+ rings), commit
  only with his explicit approval (per this project's standing rule: no
  `git commit` without current, explicit sign-off, even after earlier
  approvals in the same session).

## Explicitly deferred / out of scope for v1

- GPU compute-shader geometry (moving `ring_geometry.py`'s math onto the
  GPU itself) -- the CPU-numpy recompute-on-N-change already tested fine at
  20M+ rings; only worth revisiting if a future need requires smooth
  per-frame N animation (not just navigation) at that scale.
- Video/animation export parity with Structural Sieve's own Stage 6 -- see
  Faza 6+ section below, where this is revisited (not silently dropped) now
  that the goal has widened to full feature parity.

## Faza 6+ -- Full feature parity with the HTML reference (branch `ring-outline-drawing`, 2026-09-05)

**Goal, restated by Artur (2026-09-05):** the ring visualization in PrimeAtlas
should support exactly the same functions as the browser Structural Sieve
(`StructuralSieve.html` / `StructuralSieveApp.js` / `DrumRenderer.js` /
`SieveModel.js` in the RelationalMathematics repo), just usable at far
larger N/ring counts than a browser tab can reach -- not a subset, and not
a reinterpretation. Faza 0-5 (done, merged to `main`) covered the raw ring
field, window highlight colors, and navigation/zoom. This section is a full
audit of the HTML reference's UI (`StructuralSieve.html`'s controls) against
current PrimeAtlas state, turned into a dependency-ordered phase list.

**Audit method:** two passes. First pass read every `<button>`/`<input>`/
`<select>` in `StructuralSieve.html` plus the JS methods each one wires to.
**Second pass (2026-09-05, prompted by Artur suspecting the first pass
undercounted the reference's real feature set)** read the full method
inventory of all three JS files directly (every `methodName(...) {` in
`StructuralSieveApp.js`/`DrumRenderer.js`/`SieveModel.js`, not just the ones
reachable from a visible UI control) -- this caught two real gaps the
control-only pass missed: `triggerBirthFlash()` (a distinct flash from
`triggerResonanceFlash()`, fires when a new prime ring is born) and
`#drawCenterMarker` (a small always-drawn marker at the ring field's
origin). Both folded into Faza 8 below. Cross-checked the full method list
against `renderer.py`/`ring_geometry.py`'s current code -- all came back
with zero matches for the still-missing ones, confirming they're genuinely
not ported, not just named differently.

**Gap list, in dependency order:**

**Faza 6 -- Tracked-primes foundation ("Track P")**
- `--track-primes` CLI arg + a launch-time "Track P" field in `rings_tab.py`
  (same restart-to-change pattern as the existing N/windows/point-size
  fields -- see Faza 3's own "no live IPC into the running subprocess"
  precedent).
- Pure filter (ring_geometry.py or renderer.py): which of the entered
  primes are actually active at the current N.
- Also folds in `#advanceAutoOrbit`'s mode (JS: when nothing is explicitly
  tracked, auto-cycle through active primes one at a time) as a
  `--auto-orbit` flag -- same "what's tracked" bucket, and only meaningful
  once Faza 10's playback loop exists to advance through, so implement the
  flag/state here but its visible effect waits on Faza 10.
- This is a **shared prerequisite** for Faza 7 and Faza 8 below -- both the
  LCM/resonance HUD and the outline circles need "which primes are tracked
  and currently active" as their input. Build it once, here, rather than
  twice.

**Faza 7 -- Tracked-primes LCM/resonance HUD**
- Ports `#trackedResonanceState` / `#lcmOfTracked` / `#buildLcmLines` /
  `#formatBig` (see this file's git history for the fuller design note
  written 2026-09-04 on the `ring-viz-lcm-resonance` branch -- the mask/
  lookup-table idea does NOT apply here, JS's own tracked-prime cap
  defaults to 500, a bitmask table is only tractable in the teens/twenties).
  Straight port: product-based LCM (pairwise coprime), cached by the
  tracked-and-active list's content, HUD lines via the console pane.

**Faza 8 -- Tracked-ring outline circles (task #595)**
- [VERIFIED against source, 2026-09-05] `DrumRenderer.js` draws a full
  circle stroke (`ctx.arc(...).stroke()`) ONLY for `ring.tracked` rings --
  NOT for every ring. Non-tracked rings only ever get their hit-tooth dot
  (draw()'s ring loop, `if (ring.tracked) { ...stroke... }` gates the
  circle; `#drawRingTeeth` runs unconditionally for the dot). So this phase
  needs Faza 6's tracked list, not a blanket "outline every ring" change.
- Color: gray (`rgba(180,180,180,0.5)`) by default, or the ring's own
  `trackedColor` (which window family picked this exact prime as its
  anchor -- already computed by Faza 1's highlight-color logic) when more
  than one window family is active at once.
- New GL work: current renderer only draws `GL_POINTS` (see
  `build_vertex_data`) -- circle outlines need a second draw call
  (`GL_LINE_LOOP` per tracked ring, or a triangle-strip ring mesh), a new
  shader/VAO path alongside the existing points pass, not just new vertex
  color data. This is the one phase in this list with real new
  rendering-pipeline work, not just new pure-Python math plus a stdout line.
- [ADDED after the second-pass audit above] Also covers the two flash
  overlays (`triggerBirthFlash`/`triggerResonanceFlash` -- a screen-wide
  translucent color wash, decaying each frame, `*= 0.65` per the JS) and
  `#drawCenterMarker` (a small always-on marker at the ring field's
  origin) -- all three are the same class of work (new draw calls in the
  existing GL loop, no new pure-math needed: `ring_geometry.py` already has
  every anchor/color function this phase touches --
  `bertrand_anchor_at`/`legendre_anchor_at`/`general_law_anchor_at`/
  `compute_tracked_colors` all landed in Faza 1, confirmed present by
  `grep`). Birth-flash needs one small new bit of state (did the active-ring
  count grow since the last frame) -- everything else in this phase is
  pure rendering plumbing over already-ported math.

**Faza 9 -- Load Range (auto-track a whole loaded range)**
- Ports `#loadPrimeRange`: From/To fields + a "Load Range" button in
  `rings_tab.py`, auto-populating Faza 6's Track P list with every prime in
  the range (capped the same way Faza 7's `max_tracked` already caps single
  entries).

**Faza 10 -- Playback / navigation controls**
- START/STOP: auto-advance N over time inside the GL render loop at a
  configurable speed (mirrors the HTML's tempo slider).
- RESET: return to the N the renderer was launched with.
- GOTO N already effectively exists (the N field + relaunch) -- decide
  whether a live in-window goto (no relaunch) is worth the same live-IPC
  investment flagged for Track P in Faza 6, or whether relaunch-to-jump
  stays the standing convention for this renderer.

**Faza 11 -- Resonance log + primes list panels**
- `ring_geometry.resonance_events_in_range` already exists (landed in
  Faza 1) -- this phase is wiring it to output, not new math. Port
  `#resonanceLog` (text log of "N = factor x factor..." entries) and the
  primes/surviving-list panel to the console pane, same precedent as
  Faza 4's HUD text.

**Faza 12 -- Live audio (tone synth)**
- Integration implementation (GPT, 2026-09-10): optional
  `--audio` with `--sound-low`, `--sound-prime`, `--sound-lcm`, plus translated
  launch-time controls in RingsTab. Install `sounddevice` in the same Python
  used to launch Atlas (`python -m pip install sounddevice`); NumPy is already
  a renderer dependency. Missing backend/device leaves visualization running
  silently with a console explanation. Defaults: sound off, sine/triangle/choir.
- Event hook reuses the computed hit mask and tracked-LCM HUD state only on
  advancing ticks. It inspects at most the audible active-index prefix, not
  an additional full ring array; eight voices/events bound callback work.
  Audio closes in a finally block, including renderer failure. High-frequency
  partials are omitted and waveforms approximate browser oscillators.
- Validation: eight audio/integration tests, geometry/renderer checks and real
  Tk tab tests passed. The full-app Tk test also emitted an unrelated settings
  update-thread warning (`main thread is not in main loop`). Artur confirmed
  audible playback on 2026-09-10 after sounddevice was installed in his Python
  3.13 environment. A direct device smoke test had no callback errors. Detailed
  perceptual parity remains unverified; no WAV/MIDI export added.
- Ports `ToneSynth.js`'s trigger logic (note on hit / tracked-prime /
  LCM-resonance) to a Python audio backend (e.g. `sounddevice`) plus
  instrument selection (the HTML's `soundLow`/`soundPrime`/`soundLCM`
  selects). **Flagged as the highest-risk phase in this list**: there is no
  existing audio code anywhere in PrimeAtlas to build on, unlike every
  other phase above which extends an already-proven pattern (CLI arg +
  Tk field, pure function + cache, stdout line, or a second GL draw call).

**Faza 13 -- WAV / MIDI export [CUT, Artur 2026-09-05: "wideo i eksport na
tę chwilę sobie darujmy"]**
- Was: offline (non-realtime) render reusing Faza 12's trigger logic.
  Explicitly out of scope for now, same decision as video export below --
  not silently dropped, decided. Revisit only if Artur asks again later.

**Faza 14 -- Fullscreen toggle**
- Small, likely a single `glfw` window-mode call. Independent of everything
  above -- can be slotted in whenever convenient, including before Faza 6
  if a quick low-risk win is wanted first.

**Video/animation export (WebM/MP4 RECORD button) -- [CUT, Artur 2026-09-05:
"wideo i eksport na tę chwilę sobie darujmy"].** Was flagged as a real new
subsystem (frame capture + encoding) with nothing existing in PrimeAtlas to
build on. Decided out of scope for now, same as Faza 13 above. Revisit only
if Artur asks again later.

**Sequencing note:** Faza 6 must come before Faza 7, 8, and 9 (shared Track
P prerequisite; Faza 6's auto-orbit flag also waits on Faza 10 for its
visible effect). Faza 10, 11, 12, and 14 have no dependency on each other
and can be reordered freely if Artur wants a different priority. (Faza 13's
former dependency on Faza 12 is moot now that Faza 13 is cut.)
