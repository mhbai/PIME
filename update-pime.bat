@echo off
REM Update this PIME installation to the latest tracked commit on GitHub, then
REM restart the backend so the new code actually takes effect - requires
REM Administrator privileges (git reset --hard writes under Program Files,
REM and restart-pime-backend.bat needs it too).
REM
REM Steps: git fetch + reset --hard origin/master (same overlay method used
REM for the initial install, see README.md), then calls
REM restart-pime-backend.bat so the old backend process is killed and a
REM fresh one starts and picks up the updated code/table. Deliberately does
REM NOT call unregister-pime.bat/register-pime.bat here: repeatedly
REM re-registering the TSF text service via regsvr32 has been observed to
REM reset Windows' currently-selected input method for the language back to
REM whichever TIP was just re-registered, knocking the user out of whatever
REM other IME they had selected - and it's unnecessary anyway, since pulling
REM new cheliu Python code never requires re-registering the already-
REM installed COM/TSF component, only restarting the backend process.
REM
REM Refuses to overwrite local changes silently: if git status shows anything
REM dirty (tracked-file edits or untracked files under the tracked paths),
REM this script stops before touching anything so nothing is lost by
REM accident.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script requires Administrator privileges.
    echo Right-click update-pime.bat and choose "Run as administrator".
    pause
    exit /b 1
)

set "DIR=%~dp0"
cd /d "%DIR%"

echo Fetching latest changes from GitHub...
git fetch origin
if %errorlevel% neq 0 (
    echo [ERROR] git fetch failed ^(exit code %errorlevel%^). Check your network/login and try again.
    pause
    exit /b 1
)

git status --porcelain > "%TEMP%\pime-update-status.txt"
for %%A in ("%TEMP%\pime-update-status.txt") do set STATUS_SIZE=%%~zA
del "%TEMP%\pime-update-status.txt" >nul 2>&1
if not "%STATUS_SIZE%"=="0" (
    echo [ERROR] This checkout has local changes that "git reset --hard" would discard.
    echo Run "git status" to see what they are, then commit/stash them first.
    pause
    exit /b 1
)

echo Resetting to origin/master...
git reset --hard origin/master
if %errorlevel% neq 0 (
    echo [ERROR] git reset --hard failed ^(exit code %errorlevel%^).
    pause
    exit /b 1
)

echo.
echo Restarting PIME backend so the update takes effect...
call "%DIR%restart-pime-backend.bat"

echo.
echo Update complete.
