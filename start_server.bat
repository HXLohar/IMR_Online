@echo off
cd /d "%~dp0server"
python -m uvicorn app:app --reload --port 8000
pause
