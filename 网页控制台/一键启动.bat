@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PORT=8765
set LOG=%~dp0server.log
set PY=C:\Users\HP\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe
if not exist "%PY%" set PY=C:\Users\HP\.workbuddy\binaries\python\versions\3.13.12\python.exe
if not exist "%PY%" set PY=python
if not exist "%PY%" set PY=py
if not exist "%~dp0tree_server.py" (
  echo ERROR: tree_server.py not found in this folder
  pause
  exit /b 1
)
"%PY%" --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python not found: %PY%
  pause
  exit /b 1
)
start "AIMH-Backend" cmd /c ""%PY%" "%~dp0tree_server.py" %PORT% > "%LOG%" 2>&1"
set /a WAIT=0
:loop
timeout /t 1 >nul
netstat -ano 2>nul | find ":%PORT% " | find "LISTENING" >nul
if not errorlevel 1 goto :up
set /a WAIT+=1
if %WAIT% LSS 15 goto :loop
echo Backend did not start within %WAIT%s. Check %LOG%
if exist "%LOG%" notepad "%LOG%"
pause
exit /b 1
:up
start "" "http://127.0.0.1:%PORT%/"
echo Console started. Closing browser will NOT stop backend.
echo To stop backend, kill python in Task Manager.
echo Log: %LOG%
echo.
echo Console started. This window will close in 2 seconds (backend keeps running).
timeout /t 2 >nul
