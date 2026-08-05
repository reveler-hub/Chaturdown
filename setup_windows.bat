@echo off
setlocal

echo Chaturdown (Windows) - Setup
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH. Install it from https://www.python.org/downloads/
    echo         and make sure "Add python.exe to PATH" is checked during install.
    goto :error
)

if not exist Chaturdown_Venv (
    echo Creating virtual environment...
    python -m venv Chaturdown_Venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        goto :error
    )
)

echo Installing dependencies...
call Chaturdown_Venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate the virtual environment.
    goto :error
)

python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency install failed. See the output above.
    goto :error
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo.
    echo [WARNING] ffmpeg was not found on PATH. Chaturdown.py uses it to
    echo           merge/convert downloads. Grab a build from https://www.gyan.dev/ffmpeg/builds/
    echo           and add its bin\ folder to PATH.
)

echo.
echo Setup complete!
echo.
echo Next steps:
echo   1. Export your Chaturbate cookies as a Netscape-format .txt file (e.g. via a browser extension).
echo   2. Save it as Chaturdown_Cookies.txt in this folder.
echo   3. Edit the configuration section at the top of Chaturdown.py.
echo   4. Just double-click Chaturdown.py to run it — it automatically
echo      relaunches itself under Chaturdown_Venv's own Python, so this venv
echo      doesn't need to be activated or targeted manually.
echo.
pause
endlocal
exit /b 0

:error
echo.
echo Setup did not finish. See the error above.
echo.
pause
endlocal
exit /b 1
