"""Generation stop request shared by the GUI (writes it) and the orchestrators (read it).

The GUI stops an orchestrator run with a save point: it writes STOP_REQUEST_FILENAME in
the storage folder and kills only the scanner processes (scanner_script() of the engine),
so the orchestrator survives, sees the request and logs what was written
(CLOSE_GUARD_PLAN.md). The GUI deletes the file after the run exits and before every
launch; the orchestrators only read it, since parallel instances share it.

No tkinter and no primeatlas imports: this module runs inside WSL next to the scanners.
"""
import os

STOP_REQUEST_FILENAME = "GENERATION_STOP_REQUEST.txt"

# Scanner script per orchestrator engine (orchestrator_v3.SCANNER_VERSION values).
SCANNER_SCRIPTS = {
    "v3": "prime_sieve_v3.py",
    "v4": "prime_sieve_v4.py",
    "v4.1": "prime_sieve_v4_1.py",
    "v5": "prime_sieve_v5_2.py",
    "v6": "prime_sieve_v6_1.py",
    "pt1": "prime_sieve_pt1.py",
}


def scanner_script(engine):
    """Scanner script filename of `engine`; KeyError for an unknown engine."""
    return SCANNER_SCRIPTS[engine]


def stop_request_path(portal_folder):
    return os.path.join(portal_folder, STOP_REQUEST_FILENAME)


def stop_requested(portal_folder):
    return os.path.exists(stop_request_path(portal_folder))


def stop_request_time(portal_folder):
    """Modification time of the stop request (unix seconds), or None when there is none."""
    try:
        return os.path.getmtime(stop_request_path(portal_folder))
    except OSError:
        return None
