# Module: visualization (Visualization tab and GPU renderer)

The Visualization tab's sub-tabs (Rings, Tree, Sphere) each launch the shared renderer
(`shared/renderer.py`, moderngl/GLFW) as a native Windows subprocess in its own `--viz-mode`, and
exchange state with it over stdout (HUD JSON) and stdin (RESUME).

## Files

| Part | Files |
|---|---|
| Registry | `primeatlas/visualization/mode_registry.py` (`MODES`: rings, line, tree, assembly, sphere, sphere_fibers) |
| Shared renderer | `shared/renderer.py`, `renderer_cli.py`, `renderer_launch.py`, `renderer_frame.py`, `session.py`, `sources.py`, `range_data.py`, `playback.py`, `hud_text.py`, `draw_primitives.py`, `audio.py`, `stdin_commands.py`, `gl_setup.py`, `viz_tab_base.py` |
| Rings | `rings/rings_tab.py`, `rings/pattern_source.py` (line mode's pattern switch), `rings/ring/` (geometry, windows, anchors, colors, resonance, tracked, draw, HUD), `rings/line/` (line mode, k-tuple pattern seek) |
| Tree and assembly | `tree/`, `assembly/` |
| Sphere | `sphere/` (rings and fibers modes) |

## Contract

| In | Out |
|---|---|
| sub-tab form values, storage path | renderer subprocess; HUD state back into the tab; resume point |

`shared/` never names a concrete mode; adding a mode is one `MODES` entry. No GL import outside
`run()`, so every pure-logic part is testable without a GPU.

Line mode's pattern has three sources (`PatternSource`, a radio switch that shows only the chosen
mode's controls). From the list, the default, is the catalog's `PatternPicker` (k, then variant)
and launches `--pattern-offsets 0,2,6,8`; the renderer rejects offsets that are not 0-first,
strictly ascending and admissible (`line_geometry.is_admissible`: no prime p <= k has every
residue hit) and anchors the pattern at the first wheel candidate in the loaded window. Manual
takes k and p0 and launches `--pattern-seed-k/--pattern-seed-start`; a preview under the fields
shows the offsets on every keystroke and names the catalog pattern they match, up to p0 = 10^9 and
k = 100 (`PREVIEW_P0_MAX`, `PREVIEW_K_MAX`: trial division; arbitrary bounds), past them the
window computes them at launch. None launches no pattern; ring mode never sends one. The three
radios, both dropdowns and the k/p0 fields lock while the renderer is paused.

## Parameters and texts

[visualization-renderer](../parameters/visualization-renderer.md); texts `rings.*`, `tree.*`, `sphere.*`.

## Kept data

Each sub-tab's last values in `app_settings.json`; nothing in the storage folder. Rings saves
the pattern mode (`pattern_source`), the list's `pattern_list_k`/`pattern_list_id` and Manual's
`pattern_k`/`pattern_p0` separately; a save without a mode opens Manual when it holds a k or p0,
else From the list.

## Specs and tests

`test_rings_tab`, `test_rings_tab_argv`, `test_rings_pattern_source`, `test_ring_geometry`, `test_ring_window_colors`,
`test_ring_resonance`, `test_ring_viz_sources`, `test_ring_viz_draw`, `test_ring_viz_renderer`,
`test_ring_viz_session`, `test_ring_viz_pattern_mode`, `test_ring_viz_pattern_offsets`, `test_ring_viz_pattern_seek`,
`test_ring_viz_pattern_seek_async`, `test_ring_audio`, `test_ring_fullscreen`, `test_tree_*`,
`test_assembly_*`, `test_sphere_*`, `test_fiber_geometry`, `test_fibers_mode`, `test_world_labels`.

## Known gaps

None.
