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
- Video/animation export parity with Structural Sieve's own Stage 6 -- a
  separate feature, not blocking the "interactive navigation at large
  scale" goal this whole investigation started from.
