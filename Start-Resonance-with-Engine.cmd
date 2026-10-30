@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Run Install-Resonance.cmd first.
 pause
 exit /b 1
)
start "Resonance Engine" cmd /c ""%~dp0Start-Engine.cmd""
".venv\Scripts\python.exe" launch_engine.py --wait-ready
if errorlevel 1 (
 echo The engine was not ready. Check its console before starting Resonance.
 pause
 exit /b 1
)
call Start-Resonance.cmd
