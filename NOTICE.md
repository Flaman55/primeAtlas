# NOTICE

PrimeAtlas is distributed under the PolyForm Noncommercial License 1.0.0 (see
`LICENSE.md`).

Required Notice: Copyright 2026 Artur Flamandzki (https://github.com/Flaman55/primeAtlas)

PrimeAtlas uses or can work with the independent third-party projects below. None of them
is part of PrimeAtlas's own source code, and each keeps its own license.

## Libraries used by the app

- **primesieve** -- Kim Walisch, https://github.com/kimwalisch/primesieve, BSD 2-Clause
  License. Linked at runtime (`libprimesieve`, installed inside WSL) by the primesieve
  generation mode and the primesieve calculator; not included in this repository.
- **primecount** -- Kim Walisch, https://github.com/kimwalisch/primecount, BSD 2-Clause
  License. Optional; the pi(x) approximations tab's "primecount" data source calls
  `libprimecount`, installed on request inside WSL; not included in this repository.
- **CUDASieve** -- Curtis Seizert, https://github.com/curtisseizert/CUDASieve, GNU GPLv3.
  Optional; built from its own repository on request (after showing its license) and run
  only as a separate process, never linked into or distributed with PrimeAtlas.

Python packages installed from PyPI by pip (by the installer or the app's own startup
check), each under its own license: numpy (BSD 3-Clause), moderngl (MIT), glcontext (MIT),
glfw / pyGLFW (MIT; bundles the GLFW library, zlib/libpng License), and optionally sympy
(BSD 3-Clause), sounddevice (MIT), Pillow (MIT-CMU).

## Components bundled in the Windows installer (PrimeAtlasSetup.exe)

The installer redistributes two unmodified third-party runtimes, installed next to the app:

- **Python 3.13** (CPython, the official python.org ZIP package) -- Copyright Python
  Software Foundation, Python Software Foundation License Version 2. Its full license text
  is installed as `python\LICENSE.txt`. Source: https://www.python.org/downloads/source/
- **MinGit** (portable Git for Windows, used for the app's self-update) -- Git for Windows
  project, https://gitforwindows.org/. Git itself is licensed under the GNU GPL version 2;
  MinGit also contains components under other licenses. Their license texts are installed
  as `git\LICENSE.txt`. The complete corresponding source code of the exact bundled version
  is available from the release tag `v2.56.0.windows.1`:
  https://github.com/git-for-windows/git/releases/tag/v2.56.0.windows.1
  (and https://github.com/git-for-windows for the build infrastructure).
