@echo off
title IMR Online

start "IMR Server" cmd /k "cd /d "%~dp0server" && python -m uvicorn app:app --reload --port 8000"

timeout /t 1 /nobreak > nul
start "IMR Client" cmd /k "cd /d "%~dp0client" && npx vite --port 5173"

timeout /t 3 /nobreak > nul
start http://localhost:5173
