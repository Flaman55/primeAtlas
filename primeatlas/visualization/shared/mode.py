"""
mode.py -- VizMode, the interface between the shared RenderSession/renderer loop and
one visualization mode (rings, line, ...). A mode owns its own state and turns the
session's current N into vertex data, HUD lines and overlay draws; the session owns
everything common to all modes (N, playback, scrub, camera, HUD snapshot, buffer
extension, the sliding range window, the background seek).

Every hook has a neutral default here, so a mode overrides only what it actually
changes. Nothing here imports moderngl or glfw.

Launch-time hooks (classmethods) let a mode own its CLI arguments: renderer.py's
main() calls add_arguments/validate_arguments on EVERY registered mode, and
_run_visualization calls prepare_launch on every mode once the primes are loaded,
merging the returned dicts into RenderSession's launch config.
"""


class LaunchAborted(Exception):
    """Raised by a mode's prepare_launch when the window must not open; the message
    is printed by the renderer."""


class VizMode:
    """Base class for one visualization mode.

    `session` is the owning RenderSession; `config` is the launch-time keyword dict
    RenderSession was constructed with (each mode reads only its own keys)."""

    name = None

    def __init__(self, session, config):
        self.session = session

    # -- launch -----------------------------------------------------------------

    @classmethod
    def add_arguments(cls, parser):
        """Adds this mode's own CLI arguments to the renderer's argparse parser."""

    @classmethod
    def validate_arguments(cls, parser, args):
        """Fail-fast validation of this mode's own arguments (parser.error on a bad
        value). Called for every registered mode, whichever --viz-mode is active."""

    @classmethod
    def prepare_launch(cls, args, launch):
        """Turns parsed `args` into this mode's RenderSession config keys, once the
        primes are loaded. `launch` carries the resolved launch state (primes, n,
        range_mode, range_primes); a mode may move `launch.n`. Raises LaunchAborted
        when the window must not open. Returns a dict merged into the session's
        launch config."""
        return {}

    # -- frame data -------------------------------------------------------------

    def rebuild(self, n_value, prev_ring_count=None, advancing=False, audio=None):
        """Recomputes everything N-dependent for `n_value` and updates the session's
        HUD snapshot (hud_n/hud_count/hud_rebuild_ms/hud_lines). Returns
        (data_normal, data_hit, count, count_hit): two vertex arrays for the
        renderer's two point draw calls (see split_hit_normal_vertex_data)."""
        raise NotImplementedError

    def outline_draws(self):
        """(radius, rgba) circle outlines to draw over the shared unit circle."""
        return []

    def axis_boundary_radius(self):
        """Radius of the radial boundary line to draw this frame, or None."""
        return None

    def flash_overlays(self):
        """[(rgba, decay_callable)] full-screen flash overlays to draw this frame, in
        draw order; each decay_callable is invoked right after its overlay is drawn."""
        return []

    def hud_line_colors(self, canvas_lines):
        """Per-line RGB colors for the on-canvas HUD text, or None for the default
        color on every line."""
        return None

    # -- navigation -------------------------------------------------------------

    def clamp_n(self, n):
        """Clamp applied after a plain (non-mode-specific) N step."""
        return n

    def tick(self):
        """Mode-specific playback tick. None = not handled (the session's plain tick
        runs); otherwise True if playback stopped, False if N advanced."""
        return None

    def bump_n(self, delta):
        """Mode-specific Up/Down/PageUp/PageDown step. True if handled."""
        return False

    def scrub(self, is_right, ctrl_held):
        """Mode-specific Left/Right step. True if handled."""
        return False

    # -- session events ---------------------------------------------------------

    def on_chunks_changed(self):
        """Called after the session's sliding window swapped or reloaded chunks."""

    def reset_state(self):
        """Resets this mode's own state on R (the session resets the shared part)."""
