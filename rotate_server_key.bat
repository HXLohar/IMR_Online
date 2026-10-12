@echo off
setlocal
set "IMR_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%IMR_PYTHON%" set "IMR_PYTHON=py"
pushd "%~dp0server"
"%IMR_PYTHON%" rotate_server_key.py
set "IMR_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %IMR_EXIT%
