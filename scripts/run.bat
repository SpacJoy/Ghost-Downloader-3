@echo off
rem Interactive launcher menu. Pass a mode to skip the menu, e.g. run.bat log
rem Modes: bg fg log list kill package (e.g. run.bat package -Version 4.6.1 -Installer)
setlocal
set "PS=powershell"
where pwsh >nul 2>nul && set "PS=pwsh"
rem pwsh handles UTF-8 without BOM; Windows PowerShell 5.1 needs the BOM that run.ps1 ships with
rem No arguments means either a double-click (cmd /c closes the window on exit and the
rem last line flashes by) or the interactive menu; in both cases keep the window open at
rem the end. Runs with arguments are scripted, so exit straight through.
set "PAUSE_ON_EXIT="
if "%~1"=="" set "PAUSE_ON_EXIT=1"

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 set "PAUSE_ON_EXIT=1"
if defined PAUSE_ON_EXIT pause
endlocal
