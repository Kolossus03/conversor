@echo off
rem Removes Conversor shortcuts, settings, cache and AI models. Asks before deleting anything.
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\uninstall.py"
