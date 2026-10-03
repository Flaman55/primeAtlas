"""
shared -- infrastructure common to every GPU-rendered visualization. `renderer.py` is a
standalone-runnable module (launched as a subprocess by each visualization sub-tab, e.g.
primeatlas/visualization/rings/rings_tab.py) rather than something imported directly into
the main Tkinter process: GL's own event loop does not compose with Tkinter's
`mainloop()`, so it runs as a separate process.
"""
