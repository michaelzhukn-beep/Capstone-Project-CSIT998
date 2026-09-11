@echo off
rem Switch the console to UTF-8 so Python's Chinese banner (which carries
rem the public URL) renders instead of turning into mojibake.
chcp 65001 >nul
rem ============================================================
rem  Real Estate Assistant - share it on the internet.
rem  Starts the web server (if it is not already running) and opens
rem  a Cloudflare Quick Tunnel, then prints the public address.
rem  Close this black window to stop sharing.
rem
rem  NOTE: keep this file PURE ASCII, no Chinese characters.
rem  cmd.exe reads .bat files in the OEM code page (936 on a Chinese
rem  Windows). UTF-8 comments get mis-decoded and cmd then tries to
rem  RUN fragments of them - seen for real: "'OEM' is not recognized".
rem  Python prints the Chinese banner, so nothing is lost.
rem ============================================================

cd /d "%~dp0"

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
"%PYEXE%" share.py %*

echo.
echo Sharing stopped.
pause
