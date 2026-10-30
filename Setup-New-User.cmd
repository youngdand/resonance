@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Run Install-Resonance.cmd first.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" setup_user.py
pause
