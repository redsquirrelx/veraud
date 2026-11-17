@echo off
setlocal
set "SUITE_ROOT=%~dp0"
if "%SUITE_ROOT:~-1%"=="\" set "SUITE_ROOT=%SUITE_ROOT:~0,-1%"
where uv >nul 2>nul
if errorlevel 1 (
  echo [tallercito] ERROR: 'uv' no encontrado en PATH. Instale uv o use: uv run --project "%SUITE_ROOT%" python "%SUITE_ROOT%\runner.py" 1>&2
  exit /b 2
)
if exist "%SUITE_ROOT%\uv.lock" (
  set "LOCK=--locked"
) else (
  set "LOCK="
  echo [tallercito] Aviso: la suite no incluye uv.lock resuelto; la resolucion de dependencias no es reproducible. 1>&2
)
uv run --project "%SUITE_ROOT%" %LOCK% python "%SUITE_ROOT%\runner.py" %*
exit /b %ERRORLEVEL%
