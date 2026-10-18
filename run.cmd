@echo off
setlocal
set "AUTOLOG_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%AUTOLOG_PYTHON%" set "AUTOLOG_PYTHON=%LOCALAPPDATA%\AutoLog\development\venv314\Scripts\python.exe"
if not exist "%AUTOLOG_PYTHON%" set "AUTOLOG_PYTHON=%LOCALAPPDATA%\VILLogging\development\venv314\Scripts\python.exe"
if not exist "%AUTOLOG_PYTHON%" (
  echo Project Python environment is missing. See CONTRIBUTING.md for Python 3.14 x64 setup.
  pause
  exit /b 1
)
set "PYTHONPATH=%~dp0src"
set "PYTHONDONTWRITEBYTECODE=1"
"%AUTOLOG_PYTHON%" -m vil_logging %*
exit /b %errorlevel%
