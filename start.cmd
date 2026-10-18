@echo off
setlocal
cd /d "%~dp0"
if not defined PI_KIT_RUNTIME_HOME set "PI_KIT_RUNTIME_HOME=%~dp0.tools\python-runtime"
call "%~dp0kit\python.cmd" -m kit.run_pi %*
set "kit_result=%errorlevel%"
if not "%kit_result%"=="0" pause
exit /b %kit_result%
