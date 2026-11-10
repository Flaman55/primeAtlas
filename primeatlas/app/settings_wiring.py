"""
settings_wiring.py -- SettingsWiringMixin of PortalBrowserApp: the storage-path setter
and the 'Settings' tab, built with the callable bundle (wsl_helpers) through which
SettingsTab reuses the Generation tab's WSL launch machinery.
"""
from primeatlas.app import app_dynamic as _dyn
from primeatlas import try_import_sympy as primality_try_import_sympy
from primeatlas.core import ui_state_dynamic
from primeatlas.core.storage import LOW_FLOOR_CUTOFF
from primeatlas.generation.engine_argv import (
    build_loop_argv, build_constellation_finder_argv, build_primesieve_argv,
    build_pip_install_argv, build_cudasieve_status_argv, build_cudasieve_fetch_license_argv,
    build_cudasieve_build_argv, build_primecount_query_argv, build_env_versions_argv,
    build_pseudosquares_install_argv,
)
from primeatlas.generation.generation_settings import load_generation_settings
from primeatlas.generation.logged_runners import WslLoggedRunner, LocalLoggedRunner
from primeatlas.generation.window_planning import (
    PRIMESIEVE_MAX_STOP, find_continuation_target_idx,
)
from primeatlas.generation.wsl_blocking import (
    run_cudasieve_wsl_blocking, run_primecount_wsl_blocking, run_primecount_install_wsl_blocking,
    run_env_versions_wsl_blocking, run_pseudosquares_status_wsl_blocking,
    run_pseudosquares_tools_install_wsl_blocking,
)
from primeatlas.generation.wsl_command import build_wsl_logged_command, generation_log_paths
from primeatlas.generation.wsl_resources import estimate_wsl_available_ram_bytes


class SettingsWiringMixin:
    # --- Tab 6: Settings -----------------------------------------------------

    def _set_portal_folder(self, new_path):
        """The one place that rebinds _dyn.PORTAL_FOLDER (app_dynamic.py) -- passed into
        SettingsTab as wsl_helpers["set_portal_folder"] so a storage-path change in the
        Settings tab takes effect immediately for every tab, all of which read
        _dyn.PORTAL_FOLDER at call time.

        Rebinding the global alone isn't enough: without an explicit reload, a
        genuinely empty new location would still show the previous location's floors
        with real file counts, since nothing else re-scans the Prime numbers /
        Constellations trees after a path change. So this re-triggers both trees'
        reload itself, right here, the moment the path actually changes (guarded by
        `changed` so re-saving the SAME path -- e.g. clicking Save again -- doesn't
        pay for two pointless re-scans). Both reload_*_tree() methods are safe to call
        here: by the time a user can reach the Settings tab's Save/Reset buttons,
        every other tab has long since finished its own initial build."""
        changed = (new_path != _dyn.PORTAL_FOLDER)
        _dyn.PORTAL_FOLDER = new_path
        self.status.set(_dyn.T("app.status_portal_initial", folder=_dyn.PORTAL_FOLDER))
        if changed:
            self.reload_primes_tree()
            self.reload_constellations_tree()

    def _build_settings_tab(self, settings_tab_cls):
        """Wires SettingsTab (primeatlas/settings/settings_tab.py) into the 5th notebook tab.
        SettingsTab doesn't know how to launch WSL subprocesses itself -- it reuses
        the Generation tab's machinery (build_loop_argv,
        build_constellation_finder_argv, build_wsl_logged_command, WslLoggedRunner,
        generation_log_paths) via this small callable bundle, rather than
        reimplementing a second copy inside primeatlas/settings/. get_loop_defaults() reads
        the Generation pipeline form's current values from the remembered-fields store
        (primeatlas/generation/generation_settings.py).

        build_wsl_logged_command here is wrapped in a lambda supplying the current
        _dyn.PORTAL_FOLDER explicitly -- primeatlas/generation/wsl_command.py's own copy of this
        function takes portal_folder as an explicit argument instead of reading a
        bare module global (see that module's own docstring for why), but
        settings_tab.py still calls this entry with the original 3-arg shape
        (argv, log_path, exit_path), so the 4th argument is supplied here rather
        than changing settings_tab.py itself."""
        wsl_helpers = {
            "get_portal_folder": lambda: _dyn.PORTAL_FOLDER,
            "set_portal_folder": self._set_portal_folder,
            "get_loop_defaults":
                lambda: load_generation_settings(ui_state_dynamic.STORE)["loop"],
            "build_loop_argv": build_loop_argv,
            "build_constellation_finder_argv": build_constellation_finder_argv,
            "build_wsl_logged_command":
                lambda argv, log_path, exit_path, extra_env=():
                    build_wsl_logged_command(argv, log_path, exit_path, _dyn.PORTAL_FOLDER,
                                             extra_env=extra_env),
            "WslLoggedRunner": WslLoggedRunner,
            "generation_log_paths": generation_log_paths,
            # For the restore driver's own RAM-based "auto width" and low-floor
            # (0-6) cascade-aware batching -- see restore_job.py / restore_section.py's
            # _drive_windows_phase() docstring. Passed through rather than imported
            # directly in restore_section.py, same reasoning as every other entry here
            # (see this method's own docstring).
            "low_floor_cutoff": LOW_FLOOR_CUTOFF,
            "estimate_wsl_available_ram_bytes": estimate_wsl_available_ram_bytes,
            # Lets the restore driver prefer primesieve mode (much faster,
            # no RAM-buffer cost) for any floor whose numeric range fits under
            # libprimesieve's own uint64 ceiling, falling back to the orchestrator
            # pipeline only for floors that don't -- see _drive_windows_phase().
            "primesieve_max_stop": PRIMESIEVE_MAX_STOP,
            "build_primesieve_argv": build_primesieve_argv,
            "find_continuation_target_idx": find_continuation_target_idx,
            # Lets SettingsTab refresh the Prime numbers / Constellations trees itself
            # after two operations that change disk contents outside those tabs' own
            # controls: deleting the entire database, and a restore job finishing --
            # otherwise emptied/regenerated floors stay invisible until a manual
            # Refresh click.
            "reload_primes_tree": self.reload_primes_tree,
            "reload_constellations_tree": self.reload_constellations_tree,
            # Optional-library installer (currently just sympy, see
            # primeatlas/primality/primality.py). LocalLoggedRunner/build_pip_install_argv are
            # plain local (non-WSL) subprocess helpers -- see their own docstrings
            # for why they don't need WslLoggedRunner's file-tailing machinery.
            "try_import_sympy": primality_try_import_sympy,
            "build_pip_install_argv": build_pip_install_argv,
            "LocalLoggedRunner": LocalLoggedRunner,
            # CUDASieve (optional GPU engine) installer -- see
            # primeatlas/generation/wsl_blocking.py's own run_cudasieve_wsl_blocking() docstring
            # for why it's NOT the plain subprocess.run(timeout=...) shape
            # run_primesieve_query_wsl() uses. Wrapped in a lambda supplying the
            # current _dyn.PORTAL_FOLDER, same as build_wsl_logged_command above, since
            # wsl_blocking.py's own copy takes portal_folder as an explicit argument
            # rather than reading a bare module global.
            "build_cudasieve_status_argv": build_cudasieve_status_argv,
            "build_cudasieve_fetch_license_argv": build_cudasieve_fetch_license_argv,
            "build_cudasieve_build_argv": build_cudasieve_build_argv,
            "run_cudasieve_wsl_blocking":
                lambda argv, timeout=120:
                    run_cudasieve_wsl_blocking(argv, _dyn.PORTAL_FOLDER, timeout),
            # primecount (Kim Walisch's exact combinatorial prime-counting library,
            # companion to primesieve above) -- on-demand installer for Settings ->
            # Updates's own primecount row (see env_setup.py's
            # REQUIRED_APT_PACKAGES comment): research-module-specific optional C
            # libraries get an on-demand button there rather than a blanket
            # first-run install. Also
            # used by research_pi_approx_tab.py's own "primecount" data-source mode
            # (imported there directly from primeatlas.generation.wsl_blocking, not through this
            # dict -- that tab has no wsl_helpers-style injection of its own, see
            # that module's own docstring) for the actual pi(x) queries; only the
            # INSTALL button itself lives in Settings.
            "build_primecount_query_argv": build_primecount_query_argv,
            "run_primecount_wsl_blocking":
                lambda argv, timeout=120:
                    run_primecount_wsl_blocking(argv, _dyn.PORTAL_FOLDER, timeout),
            "run_primecount_install_wsl_blocking":
                lambda timeout=300:
                    run_primecount_install_wsl_blocking(_dyn.PORTAL_FOLDER, timeout),
            # Pseudosquares Prime Sieve (pseudosquares_section.py): status probe, build
            # tools as root, then the build of the pinned commit on WslLoggedRunner.
            "build_pseudosquares_install_argv": build_pseudosquares_install_argv,
            "run_pseudosquares_status_wsl_blocking":
                lambda argv, timeout=60:
                    run_pseudosquares_status_wsl_blocking(argv, _dyn.PORTAL_FOLDER, timeout),
            "run_pseudosquares_tools_install_wsl_blocking":
                lambda timeout=600:
                    run_pseudosquares_tools_install_wsl_blocking(_dyn.PORTAL_FOLDER, timeout),
            # Settings -> WSL environment's component versions probe (env_versions.py).
            "build_env_versions_argv": build_env_versions_argv,
            "run_env_versions_wsl_blocking":
                lambda argv, timeout=60:
                    run_env_versions_wsl_blocking(argv, _dyn.PORTAL_FOLDER, timeout),
            # The theme/language auto-restart feature (general_section.py's
            # _has_running_job()) uses this to tell whether a Generation-tab pipeline/
            # constellation-finder/k-tuple run is currently in flight before
            # replacing the whole process via os.execv -- SettingsTab has no direct
            # reference to GenerationTab itself (same reasoning as every other entry
            # in this dict), so this is threaded through the same way. Each runner is
            # None until its first launch, hence the None-check before .is_running().
            "is_any_job_running": lambda: any(
                r is not None and r.is_running() for r in (
                    self.generation_tab_widget._loop_runner,
                    self.generation_tab_widget._const_runner,
                    self.generation_tab_widget._ktuple_runner,
                    self.generation_tab_widget._verify_runner)),
            # repo_dir for the app-update checker (primeatlas/settings/app_update.py) -- the
            # git checkout root this running process is executing out of, same value
            # AppSettings was constructed with (app_dynamic.py).
            "repo_dir": _dyn.REPO_DIR,
        }
        self.settings_tab = settings_tab_cls(
            self.settings_tab_container, _dyn.APP_SETTINGS, wsl_helpers, _dyn.TRANSLATOR)
        self.settings_tab.pack(fill="both", expand=True)
