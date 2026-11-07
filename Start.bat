@echo off
rem Startet den Siccora Launcher (vorerst aus der Test-Umgebung)
start "" "%~dp0spike\.venv\Scripts\pythonw.exe" "%~dp0app\main.py"
