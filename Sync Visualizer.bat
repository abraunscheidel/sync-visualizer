@echo off
rem Starts Sync Visualizer. Double-click to open the mouse whisker project, or drag a
rem project .yaml file onto this icon to open that project instead.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\syncviz.exe" (
    echo The Python environment was not found at "%~dp0.venv".
    echo See README.md for setup.
    pause
    exit /b 1
)

set "PROJECT=%~1"
if "%PROJECT%"=="" set "PROJECT=projects\mouse_whisker\project.yaml"

".venv\Scripts\syncviz.exe" "%PROJECT%"
if errorlevel 1 (
    echo.
    echo Sync Visualizer stopped with an error. See the message above.
    pause
)