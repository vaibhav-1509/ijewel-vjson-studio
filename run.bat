@echo off
rem Start vjson Studio 3D. Any files dropped on this .bat are opened.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m vjson_studio %*
