@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (py -3 -m venv .venv) else (python -m venv .venv)
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
 echo Dependencies installed. Run Setup-New-User.cmd for a new installation.
pause
exit /b 0
:failed
 echo Installation failed. Read the error above. Python 3.10 or later is required.
pause
exit /b 1
