@echo off
setlocal
set "AUTOLOG_BUILD_EXIT=1"
set "AUTOLOG_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%AUTOLOG_PYTHON%" set "AUTOLOG_PYTHON=%LOCALAPPDATA%\AutoLog\development\venv314\Scripts\python.exe"
if not exist "%AUTOLOG_PYTHON%" set "AUTOLOG_PYTHON=%LOCALAPPDATA%\Auto_Log\development\venv314\Scripts\python.exe"
if not exist "%AUTOLOG_PYTHON%" set "AUTOLOG_PYTHON=%LOCALAPPDATA%\VILLogging\development\venv314\Scripts\python.exe"
if not exist "%AUTOLOG_PYTHON%" goto missing_python
set "PYTHONDONTWRITEBYTECODE=1"
"%AUTOLOG_PYTHON%" -u "%~dp0packaging\build_release.py" %*
set "AUTOLOG_BUILD_EXIT=%ERRORLEVEL%"
goto finish

:missing_python
echo Python development environment is missing.
echo See CONTRIBUTING.md for Python 3.14 x64 setup.

:finish
if /i not "%~1"=="--no-pause" pause
exit /b %AUTOLOG_BUILD_EXIT%
