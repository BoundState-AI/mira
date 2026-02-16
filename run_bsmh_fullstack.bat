@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM BoundState BSMH Full-Stack Runner
REM Runs:
REM   1) Safety regression guards
REM   2) Full-stack stress harness (50 questions)
REM Optional:
REM   3) Start API server if called with: serve
REM
REM Usage:
REM   run_bsmh_fullstack.bat
REM   run_bsmh_fullstack.bat serve
REM ============================================================================

set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"

if not exist "mira\api\app.py" (
  echo [ERROR] Could not find repo root. Expected: C:\BoundState
  echo [ERROR] Current dir: %CD%
  exit /b 1
)

echo [INFO] Repo root: %CD%

REM ---- Environment defaults (override by pre-setting in shell) ----
if not defined POSTGRES_HOST set "POSTGRES_HOST=localhost"
if not defined POSTGRES_PORT set "POSTGRES_PORT=5432"
if not defined POSTGRES_DB set "POSTGRES_DB=mira"
if not defined POSTGRES_USER set "POSTGRES_USER=postgres"
if not defined POSTGRES_PASSWORD set "POSTGRES_PASSWORD=postgres"
set "PYTHONPATH=%CD%"
if not defined BSMH_BOUNCER_MODE set "BSMH_BOUNCER_MODE=haiku"
if not defined BSMH_BOUNCER_HAIKU_MODEL set "BSMH_BOUNCER_HAIKU_MODEL=claude-haiku-4-5-20251001"

echo [INFO] DB host: %POSTGRES_HOST%:%POSTGRES_PORT%  db=%POSTGRES_DB%  user=%POSTGRES_USER%
echo [INFO] BSMH_BOUNCER_MODE=%BSMH_BOUNCER_MODE%
echo [INFO] BSMH_BOUNCER_HAIKU_MODEL=%BSMH_BOUNCER_HAIKU_MODEL%
if not defined ANTHROPIC_API_KEY (
  echo [WARN] ANTHROPIC_API_KEY is not set. BSMH Haiku/Sonnet calls will fail closed.
)

REM ---- Ensure anthropic package exists (best effort) ----
py -3 -c "import anthropic" >nul 2>&1
if errorlevel 1 (
  echo [INFO] Installing anthropic package...
  py -3 -m pip install anthropic
  if errorlevel 1 (
    echo [ERROR] Failed to install anthropic package.
    exit /b 1
  )
)

echo.
echo [STEP 1/2] Running BSMH safety regression guards...
py -3 -m pytest -q -s tests\mira\test_bsmh_safety_guards.py
if errorlevel 1 (
  echo [ERROR] Safety regression guards failed.
  exit /b 1
)

echo.
echo [STEP 2/2] Running full-stack stress harness...
if exist "tmp\mira_question_pack.json" (
  py -3 tmp\mira_fullstack_stress.py --question-pack tmp\mira_question_pack.json --questions 50
) else (
  echo [WARN] tmp\mira_question_pack.json not found. Using generated questions.
  py -3 tmp\mira_fullstack_stress.py --questions 50
)
if errorlevel 1 (
  echo [ERROR] Stress harness failed.
  exit /b 1
)

echo.
echo [OK] Validation run complete.
echo [INFO] Latest report should be in: tmp\mira_fullstack_stress_*.json

if /I "%~1"=="serve" (
  echo.
  echo [STEP 3/3] Starting API server on http://localhost:8000
  py -3 -m uvicorn mira.api.app:app --host 0.0.0.0 --port 8000
)

exit /b 0
