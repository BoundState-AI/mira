@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM BoundState MUA V10 One-Shot Local Runner (Windows CMD)
REM - Kills stale listeners on 8000/8080
REM - Starts backend with explicit conda python
REM - Waits for backend health + MUA V10 ping
REM - Starts frontend with pinned API base
REM - Opens browser to /mua-v10
REM ============================================================================

set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"
if not defined MUA_BACKEND_PORT set "MUA_BACKEND_PORT=8000"
if not defined MUA_FRONTEND_PORT set "MUA_FRONTEND_PORT=8080"

if not exist "mira\api\app.py" (
  echo [ERROR] Could not find repo root from: %CD%
  echo [ERROR] Expected file: mira\api\app.py
  exit /b 1
)

set "PY_EXE="
if defined MUA_PYTHON_EXE (
  if exist "%MUA_PYTHON_EXE%" set "PY_EXE=%MUA_PYTHON_EXE%"
)

if not defined PY_EXE (
  if defined CONDA_PREFIX (
    if exist "%CONDA_PREFIX%\python.exe" set "PY_EXE=%CONDA_PREFIX%\python.exe"
  )
)

if not defined PY_EXE (
  if exist "%USERPROFILE%\.conda\envs\boundstate-intent\python.exe" set "PY_EXE=%USERPROFILE%\.conda\envs\boundstate-intent\python.exe"
)

if not defined PY_EXE (
  echo [ERROR] Could not resolve a safe Python interpreter.
  echo [ERROR] Activate your conda env first, or set MUA_PYTHON_EXE.
  echo [ERROR] Example:
  echo         set MUA_PYTHON_EXE=C:\Users\Jnwil\.conda\envs\boundstate-intent\python.exe
  exit /b 1
)

echo.
echo [INFO] Repo root: %CD%
echo [INFO] Python:    %PY_EXE%
"%PY_EXE%" -c "import sys; print('[INFO] sys.executable =', sys.executable)"
if errorlevel 1 (
  echo [ERROR] Python check failed.
  exit /b 1
)

echo.
echo [STEP 1/5] Killing stale listeners on ports %MUA_BACKEND_PORT% and %MUA_FRONTEND_PORT%...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr LISTENING ^| findstr :%MUA_BACKEND_PORT%') do (
  echo [INFO] Killing PID %%P on :%MUA_BACKEND_PORT%
  taskkill /PID %%P /T /F >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr LISTENING ^| findstr :%MUA_FRONTEND_PORT%') do (
  echo [INFO] Killing PID %%P on :%MUA_FRONTEND_PORT%
  taskkill /PID %%P /T /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo.
echo [STEP 2/5] Starting backend on http://127.0.0.1:%MUA_BACKEND_PORT% ...
set "BACKEND_CMD=%TEMP%\mua_v10_backend_%RANDOM%_%RANDOM%.cmd"
(
  echo @echo off
  echo cd /d "%CD%"
  echo set PYTHONPATH=%CD%
  echo set MIRA_AUTH_MODE=disabled
  echo "%PY_EXE%" -m uvicorn mira.api.app:app --app-dir "%CD%" --host 127.0.0.1 --port %MUA_BACKEND_PORT%
) > "%BACKEND_CMD%"
start "MIRA-MUA-V10-API" cmd /k ""%BACKEND_CMD%""

echo.
echo [STEP 3/5] Waiting for backend readiness...
set /a RETRIES=45
:wait_health
curl -s http://127.0.0.1:%MUA_BACKEND_PORT%/health | findstr /i "\"status\":\"ok\"" >nul
if not errorlevel 1 goto health_ok
set /a RETRIES-=1
if !RETRIES! LEQ 0 goto health_fail
timeout /t 1 /nobreak >nul
goto wait_health

:health_ok
echo [OK] /health is up.

curl -s http://127.0.0.1:%MUA_BACKEND_PORT%/api/mua/v10/ping | findstr /i "mua-v10" >nul
if errorlevel 1 (
  echo [WARN] /api/mua/v10/ping did not return expected payload.
  echo [WARN] Continuing anyway; check API terminal output.
) else (
  echo [OK] /api/mua/v10/ping is up.
)

echo.
echo [STEP 4/5] Starting frontend on http://localhost:%MUA_FRONTEND_PORT% ...
if not exist "frontend\package.json" (
  echo [ERROR] Missing frontend\package.json
  exit /b 1
)
set "FRONTEND_CMD=%TEMP%\mua_v10_frontend_%RANDOM%_%RANDOM%.cmd"
(
  echo @echo off
  echo cd /d "%CD%\frontend"
  echo set VITE_MUA_V10_API_BASE=
  echo set VITE_API_PROXY_TARGET=http://127.0.0.1:%MUA_BACKEND_PORT%
  echo npm run dev -- --port %MUA_FRONTEND_PORT%
) > "%FRONTEND_CMD%"
start "MIRA-MUA-V10-FE" cmd /k ""%FRONTEND_CMD%""

echo.
echo [STEP 5/5] Opening browser...
timeout /t 2 /nobreak >nul
start "" "http://localhost:%MUA_FRONTEND_PORT%/mua-v10"

echo.
echo [DONE] MUA V10 local stack launched.
echo [INFO] API Terminal:      MIRA-MUA-V10-API
echo [INFO] Frontend Terminal: MIRA-MUA-V10-FE
echo [INFO] If needed, verify:
echo        curl http://127.0.0.1:%MUA_BACKEND_PORT%/health
echo        curl http://127.0.0.1:%MUA_BACKEND_PORT%/api/mua/v10/ping
exit /b 0

:health_fail
echo [ERROR] Backend did not become healthy within timeout.
echo [ERROR] Check the MIRA-MUA-V10-API terminal for tracebacks.
exit /b 1
