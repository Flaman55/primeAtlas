"""
ring_viz -- the GPU-rendered ring/drum visualization feature (see
PLAN.md at the repo root for the phased implementation this subpackage
belongs to). `renderer.py` is a standalone-runnable module (launched as a
subprocess by primeatlas/rings_tab.py from Faza 3 onward -- see that
module's own docstring once it exists) rather than something imported
directly into the main Tkinter process: GL's own event loop does not
compose with Tkinter's `mainloop()`, so this stays a separate process on
purpose (see PLAN.md's "Window embedding" design decision).
"""
