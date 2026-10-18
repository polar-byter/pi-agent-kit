@echo off
setlocal
cd /d "%~dp0"
if not defined PI_KIT_RUNTIME_HOME set "PI_KIT_RUNTIME_HOME=%~dp0..\..\.tools\python-runtime"
call "%~dp0..\..\kit\python.cmd" -B server.py %*
