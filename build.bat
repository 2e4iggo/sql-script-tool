@echo off
rem Build dist\SQLScriptTool\SQLScriptTool.exe with Python 3.14 (where the packages are installed).
cd /d "%~dp0"
"C:\Python314\python.exe" -m PyInstaller SQLScriptTool.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo BUILD FAILED
    pause
    exit /b 1
)
echo.
echo Built: %~dp0dist\SQLScriptTool\SQLScriptTool.exe
pause
