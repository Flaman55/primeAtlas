@echo off
setlocal

rem Run_PrimeAtlas.bat -- double-click launches prime_atlas_v1.py without
rem having to type the command into a terminal by hand. Changes to the folder this
rem .bat file lives in (%~dp0), so it works regardless of where it was launched from
rem (e.g. a Desktop shortcut). prime_atlas_v1.py itself computes its own paths relative
rem to its own __file__, so this directory change is only so that "python prime_atlas_v1.py"
rem below finds the right file.

cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
    python prime_atlas_v1.py
    goto :check
)

where py >nul 2>nul
if %errorlevel%==0 (
    py prime_atlas_v1.py
    goto :check
)

echo.
echo [ERROR] Python not found in PATH ^(neither "python" nor "py"^).
echo Install Python or add it to the PATH variable.
pause
exit /b 1

:check
if not %errorlevel%==0 (
    echo.
    echo [PrimeAtlas exited with an error, code %errorlevel%]
    pause
)

endlocal
