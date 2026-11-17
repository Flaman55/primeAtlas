"""cpu_dynamic -- the CPU count WSL reports (`nproc`), shared by every thread-count field.

WSL_CPUS is None until a probe answers: the app reads it once at startup in the background,
and every later probe on the main thread (a launch, the About tab's read) refreshes it
through set_wsl_cpus(). A failed probe (None) keeps a known count: WSL that does not answer
for a moment has not lost its CPUs. Listeners (core.threads_field.ThreadsField) hear each
new count; set_wsl_cpus() runs them at once, so it is called on the Tk main thread only.
"""
WSL_CPUS = None

_listeners = []


def add_listener(listener):
    """listener(count) runs after each new count."""
    _listeners.append(listener)


def remove_listener(listener):
    if listener in _listeners:
        _listeners.remove(listener)


def set_wsl_cpus(count):
    """Stores a probe's answer; None (the probe failed) or the same count changes nothing."""
    global WSL_CPUS
    if not count or count < 1 or count == WSL_CPUS:
        return
    WSL_CPUS = count
    for listener in list(_listeners):
        listener(count)
