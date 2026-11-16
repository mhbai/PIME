@echo off
REM Restart only the PIME Python backend process - does NOT touch TSF/COM
REM registration (no regsvr32 calls). Use this after editing Python code
REM (cheliu_ime.py, cinbase, config.json, etc) to pick up the change.
REM
REM The backend process stays running indefinitely once started and never
REM auto-reloads code or config on its own, so a restart is required for any
REM change to take effect - but that restart does NOT require re-registering
REM the TSF text service, only killing and relaunching the process.
REM
REM Deliberately does NOT call regsvr32: repeatedly unregistering/registering
REM the TSF profile (what register-pime.bat/unregister-pime.bat do) has been
REM observed to reset Windows' currently-selected input method for the
REM language back to whichever TIP was just re-registered, silently knocking
REM the user out of whatever other IME (e.g. the official Boshiamy product)
REM they had selected. Use register-pime.bat/unregister-pime.bat only for
REM actual install/uninstall, not routine code-change testing - use this
REM script instead for that.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script requires Administrator privileges.
    echo Right-click restart-pime-backend.bat and choose "Run as administrator".
    pause
    exit /b 1
)

set "DIR=%~dp0"

echo Stopping any running PIME backend processes...
taskkill /F /IM PIMELauncher.exe >nul 2>&1
start /D "C:\Program Files (x86)\PIME\" PIMELauncher.exe
powershell -NoProfile -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq 'C:\Program Files (x86)\PIME\python\python3\python.exe' } | Stop-Process -Force"

echo.
echo Done. PIMELauncher.exe has been relaunched with a fresh backend process.
echo No TSF/COM registration was touched, so your currently selected input
echo method in Windows should be unaffected.
