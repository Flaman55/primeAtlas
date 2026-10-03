"""Compatibility entry point: installed shortcuts and the in-app restart name this file.
Runs prime_atlas_v2.py, the current application, as __main__."""
import os
import runpy

runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "prime_atlas_v2.py"),
               run_name="__main__")
