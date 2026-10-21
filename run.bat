@echo off
setlocal
cd /d "%~dp0"

rem Keep the environment at an ASCII-only path for Windows compatibility.
set "APP_ENV=%LOCALAPPDATA%\GoTruckContentStudio\venv"
set "VENV_PY=%APP_ENV%\Scripts\python.exe"

if not exist "%VENV_PY%" (
    if not exist "%APP_ENV%" mkdir "%APP_ENV%" >nul 2>nul
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv "%APP_ENV%"
    ) else (
        where python >nul 2>nul
        if errorlevel 1 (
            echo Python 3 is not installed or could not be found.
            echo Install Python 3.10 or newer, then run this file again.
            pause
            exit /b 1
        )
        python -m venv "%APP_ENV%"
    )
    if errorlevel 1 (
        echo Could not create the Python environment.
        pause
        exit /b 1
    )
)

"%VENV_PY%" -c "import streamlit, openai" >nul 2>nul
if errorlevel 1 (
    echo Installing required packages...
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Package installation failed. Check your internet connection and pip setup.
        pause
        exit /b 1
    )
)

"%VENV_PY%" -m streamlit run app.py --server.headless false
if errorlevel 1 pause
endlocal
