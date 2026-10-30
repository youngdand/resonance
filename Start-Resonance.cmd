@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Run Install-Resonance.cmd first to create the private Python environment.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" server.py
if errorlevel 1 (
 echo Resonance could not start. Read the error above for the actual cause.
 pause
)
