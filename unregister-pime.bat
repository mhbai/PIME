@echo off
REM Unregister PIME text service (stop/uninstall registration) - requires Administrator privileges.
REM First stops any running PIME backend processes (PIMELauncher.exe and the
REM PIME-specific python.exe), so nothing is left running with the text
REM service DLL or backend table loaded after this script finishes.
REM Then runs regsvr32 /u on both x86 and x64 PIMETextService.dll to remove the
REM COM CLSID and the Windows TSF input method profile.
REM Note: switch away from PIME as the active input method before running this,
REM otherwise the text service DLL may be in use and fail to unregister.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script requires Administrator privileges.
    echo Right-click unregister-pime.bat and choose "Run as administrator".
    pause
    exit /b 1
)

set "DIR=%~dp0"

echo Stopping any running PIME backend processes...
taskkill /F /IM PIMELauncher.exe >nul 2>&1
powershell -NoProfile -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq 'C:\Program Files (x86)\PIME\python\python3\python.exe' } | Stop-Process -Force"

echo Unregistering x86 build...
regsvr32 /u "C:\Program Files (X86)\PIME\x86\PIMETextService.dll"

echo Unregistering x64 build...
regsvr32 /u "C:\Program Files (X86)\PIME\x64\PIMETextService.dll"

echo.
echo Done.
