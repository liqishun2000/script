@echo off
setlocal
cd /d "%~dp0"
python remove_gp_check_gui.py
if errorlevel 1 pause

