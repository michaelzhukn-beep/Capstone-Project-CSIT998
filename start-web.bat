@echo off
rem Switch the console to UTF-8 so Python's Chinese banner (which carries
rem the URL) renders instead of turning into mojibake. This line must stay
rem ASCII-only like the rest of the file - see the NOTE below.
chcp 65001 >nul
rem ============================================================
rem  Real Estate Assistant - start the web UI (just double-click)
rem  Finds Python, starts the server, opens the browser when ready.
rem  Close this black window to stop the server.
rem
rem  NOTE: keep this file PURE ASCII, no Chinese characters.
rem  cmd.exe reads .bat files in the OEM code page (936 on a Chinese
rem  Windows). UTF-8 comments get mis-decoded and cmd then tries to
rem  RUN fragments of them - seen for real: "'OEM' is not recognized",
rem  "'ython' is not recognized". Python prints the Chinese banner,
rem  so nothing is lost. Do not "translate" this file back.
rem ============================================================

rem Switch to the folder this .bat lives in (= project root).
rem Without this, double-clicking from the Desktop leaves the working
rem directory at the Desktop and serve.py is not found.
cd /d "%~dp0"

rem Try, in order: the py launcher, python on PATH, then the usual
rem install locations. Relying on "python" alone fails in any terminal
rem window that was opened BEFORE Python was installed (stale PATH).
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

if not defined PYEXE (
  echo.
  echo   Python not found.
  echo   Install Python 3.12+ and tick "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

echo Using Python: %PYEXE%
echo.
"%PYEXE%" serve.py %*

echo.
echo Server stopped.
pause
