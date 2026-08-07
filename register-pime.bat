@echo off
REM Register PIME text service (start/install) - requires Administrator privileges.
REM Also stops any already-running PIME backend processes first (PIMELauncher.exe
REM and the PIME-specific python.exe), then explicitly relaunches PIMELauncher.exe,
REM so a fresh backend process starts right away and picks up any table/config
REM changes made since it was last running. Without this, an old backend
REM process can keep running for hours with a stale cin/json table in memory
REM even after files on disk are edited.
REM PIMELauncher.exe is relaunched explicitly here (rather than relying on
REM PIMETextService.dll to spawn it on demand) because on this machine the DLL
REM does not reliably launch it when an input method is activated - keys just
REM pass through as plain English with no error. Starting PIMELauncher.exe
REM directly works around that; it then starts the python backend itself.
REM Then runs regsvr32 on both x86 and x64 PIMETextService.dll to register the
REM COM CLSID and the Windows TSF input method profile.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script requires Administrator privileges.
    echo Right-click register-pime.bat and choose "Run as administrator".
    pause
    exit /b 1
)

set "DIR=%~dp0"

echo Stopping any running PIME backend processes...
taskkill /F /IM PIMELauncher.exe >nul 2>&1
start /D "C:\Program Files (x86)\PIME\" PIMELauncher.exe
powershell -NoProfile -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq 'C:\Program Files (x86)\PIME\python\python3\python.exe' } | Stop-Process -Force"

echo Registering x86 build...
regsvr32 "%DIR%x86\PIMETextService.dll"

echo Registering x64 build...
regsvr32 "%DIR%x64\PIMETextService.dll"

echo.
echo Done. Check the "Add an input method" list to confirm PIME appears.
echo PIMELauncher.exe has been relaunched and should already be running.
