@echo off
rem Interactive launcher menu. Pass a mode to skip the menu, e.g. run.bat log
rem Modes: bg fg log list kill package (e.g. run.bat package -Version 4.6.1 -Installer)
setlocal
set "PS=powershell"
where pwsh >nul 2>nul && set "PS=pwsh"
rem pwsh handles UTF-8 without BOM; Windows PowerShell 5.1 needs the BOM that run.ps1 ships with
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 pause
endlocal
