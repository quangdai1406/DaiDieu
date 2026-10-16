@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m recorder gui
if errorlevel 1 pause
