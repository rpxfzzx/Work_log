@echo off
cd /d "%~dp0"
python -m pytest -q
python worklog.py --smoke
pause
