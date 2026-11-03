# Module: visualization (Visualization tab and GPU renderer)

The Visualization tab's sub-tabs (Rings, Tree, Sphere) each launch the shared renderer
(`shared/renderer.py`, moderngl/GLFW) as a native Windows subprocess in its own `--viz-mode`, and
exchange state with it over stdout (HUD JSON) and stdin (RESUME).

## Files

| Part | Files |
|---|---|
| Registry | `primeatlas/visualization/mode_registry.py` (`MODES`: rings, line, tree, assembly, sphere, sphere_fibers) |
| Shared renderer | `shared/renderer.py`, `renderer_cli.py`, `renderer_launch.py`, `renderer_frame.py`, `session.py`, `sources.py`, `range_data.py`, `playback.py`, `hud_text.py`, `draw_primitives.py`, `audio.py`, `stdin_commands.py`, `gl_setup.py`, `viz_tab_base.py` |
| Rings | `rings/rings_tab.py`, `rings/ring/` (geometry, windows, anchors, colors, resonance, tracked, draw, HUD), `rings/line/` (line mode, k-tuple pattern seek) |
| Tree and assembly | `tree/`, `assembly/` |
| Sphere | `sphere/` (rings and fibers modes) |

## Contract

| In | Out |
|---|---|
| sub-tab form values, storage path | renderer subprocess; HUD state back into the tab; resume point |

`shared/` never names a concrete mode; adding a mode is one `MODES` entry. No GL import outside
`run()`, so every pure-logic part is testable without a GPU.

## Parameters and texts

[visualization-renderer](../parameters/visualization-renderer.md); texts `rings.*`, `tree.*`, `sphere.*`.

## Kept data

Each sub-tab's last values in `app_settings.json`; nothing in the storage folder.

## Specs and tests

`test_rings_tab`, `test_rings_tab_argv`, `test_ring_geometry`, `test_ring_window_colors`,
`test_ring_resonance`, `test_ring_viz_sources`, `test_ring_viz_draw`, `test_ring_viz_renderer`,
`test_ring_viz_session`, `test_ring_viz_pattern_mode`, `test_ring_viz_pattern_seek`,
`test_ring_viz_pattern_seek_async`, `test_ring_audio`, `test_ring_fullscreen`, `test_tree_*`,
`test_assembly_*`, `test_sphere_*`, `test_fiber_geometry`, `test_fibers_mode`, `test_world_labels`.

## Known gaps

None.
