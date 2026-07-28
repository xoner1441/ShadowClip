@echo off
setlocal
set "APP_DIR=%~dp0"
set "BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%BUNDLED_PY%" (
  set "PYTHON_EXE=%BUNDLED_PY%"
) else (
  for %%P in (python.exe) do (
    if not defined PYTHON_EXE (
      where %%P >nul 2>nul
      if not errorlevel 1 set "PYTHON_EXE=%%P"
    )
  )
)

if not defined PYTHON_EXE (
  echo Python was not found. Install Python 3.10+ or run this from the Codex desktop environment.
  pause
  exit /b 1
)

"%PYTHON_EXE%" "%APP_DIR%ShadowClip.py"
if errorlevel 1 pause
