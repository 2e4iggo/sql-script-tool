@echo off
rem Double-click launcher: always uses Python 3.14 (where the app's packages are installed),
rem and pythonw so no console window stays open.
start "" "C:\Python314\pythonw.exe" "%~dp0SQL-Generate(v4).py"
