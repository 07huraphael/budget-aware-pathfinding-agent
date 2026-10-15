@echo off
cd /d "%~dp0"
python run.py demo
if errorlevel 1 pause
