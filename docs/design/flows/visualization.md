# Flow: visualization (sub-tab form to a GPU window)

Entry points: Visualization tab, Rings / Tree / Sphere sub-tabs, "Start/Resume"
(`primeatlas/visualization/shared/viz_tab_base.py` and each `*_tab.py`).

```
 *_tab: build_renderer_argv ─> LocalLoggedRunner (native Windows python) ─> renderer.py --viz-mode <mode>
   renderer_cli.parse_args ─> renderer_launch.build_session ─> primes from sources.py (archive, sieve, synthetic, none)
   ─> renderer_frame (moderngl/GLFW) loop; HUD_STATE JSON lines on stdout ─> tab HUD panel
   window close ─> paused, waits for RESUME on stdin (--pipe-stdin-commands)
```

## Steps

| Step (module) | Runs when | Reads | Writes / does |
|---|---|---|---|
| Argv (`rings_tab.build_renderer_argv` and siblings) | Start | form fields, storage path | renderer command line ([parameters](../parameters/visualization-renderer.md)) |
| Empty-storage offer (`viz_tab_base._offer_storage_fill`) | archive source, nothing stored | storage folder | offers a generation run for the range ([generation-run](generation-run.md)) |
| Data (`shared/sources.py`, `range_data.py`) | renderer start, sliding window | PGS2 windows (`load_archive`, `load_archive_before`) | prime arrays, chunked for the sliding range window |
| Mode (`mode_registry.MODES`) | every frame | session state (`shared/session.py`) | rings, line, tree, assembly, sphere, sphere_fibers geometry |
| HUD and pause (`stdin_commands.py`, tab `_apply_hud_state`) | while running | stdout / stdin | HUD panel, N field for resume, field locks while paused |

## What leaves and what is kept

- What the user gets: a GPU window, the HUD in the tab, optional sound (`shared/audio.py`, sounddevice).
- What is stored: the sub-tab's last values in `app_settings.json`; nothing in the storage folder.

## Known gaps

- None known.
