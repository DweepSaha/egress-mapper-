@echo off
rem Start the egress mapper at http://127.0.0.1:8000 in its own window (keep this window open during the demo).
cd /d "%~dp0"
"%~dp0..\hackatlantic-prep\venv\Scripts\python.exe" scripts\serve.py
pause
