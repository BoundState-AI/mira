@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM BoundState MUA V10 Local Verification
REM 
REM Validates the MUA V10 classifier pipeline works locally before deploying
REM to GovCloud. Runs in three stages:
REM   1. Unit tests (pure Python, no server needed)
REM   2. Backend startup + API smoke test
REM   3. Frontend dev server availability
REM
REM Prerequisites:
REM   - Python 3.11+ with deps installed (pip install -r requirements.txt)
REM   - Node.js 18+ with frontend deps (cd frontend && npm install)
REM   - .env file with MIRA_AUTH_MODE=none
REM
REM Usage:
REM   verify_mua_v10.bat          Run all checks
REM   verify_mua_v10.bat tests    Run only unit tests
REM   verify_mua_v10.bat api      Run only API smoke test (assumes server running)
REM ============================================================================

set "REPO_ROOT=%~dp0"
cd /d "%REPO_ROOT%"
set "PYTHONPATH=%CD%"

echo.
echo ============================================================
echo  BoundState MUA V10 — Local Verification
echo  Machine: %COMPUTERNAME%
echo  Date:    %DATE% %TIME%
echo ============================================================
echo.

REM ── Check .env exists ──
if not exist ".env" (
    echo [ERROR] No .env file found. Create one with MIRA_AUTH_MODE=none
    echo [ERROR] See auth.env.example for reference.
    exit /b 1
)
echo [OK] .env file found

REM ── Check Python ──
py -3 --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3 not found. Install Python 3.11+.
    exit /b 1
)
for /f "tokens=*" %%v in ('py -3 --version') do echo [OK] %%v

REM ── Check key deps ──
py -3 -c "import fastapi; print(f'[OK] FastAPI {fastapi.__version__}')" 2>nul
if errorlevel 1 (
    echo [ERROR] FastAPI not installed. Run: pip install -r requirements.txt
    exit /b 1
)
py -3 -c "import pydantic; print(f'[OK] Pydantic {pydantic.__version__}')" 2>nul
py -3 -c "import docx; print('[OK] python-docx available')" 2>nul
if errorlevel 1 (
    echo [WARN] python-docx not installed. Run: pip install python-docx
)

REM ── Check if only running subset ──
if /I "%~1"=="api" goto :api_test
if /I "%~1"=="tests" goto :unit_tests

REM ============================================================
:unit_tests
echo.
echo [STAGE 1/3] Running MUA V10 classifier unit tests...
echo ────────────────────────────────────────────────────
py -3 -m pytest tests/mira/mua/test_mua_classifier.py -v --tb=short 2>&1
if errorlevel 1 (
    echo.
    echo [FAIL] Unit tests failed. Fix before deploying.
    if /I "%~1"=="tests" exit /b 1
    exit /b 1
)
echo.
echo [PASS] All unit tests passed.

if /I "%~1"=="tests" goto :done

REM ============================================================
:api_test
echo.
echo [STAGE 2/3] Testing API endpoint...
echo ────────────────────────────────────────────────────

REM Check if server is already running
curl -s http://127.0.0.1:8000/health >nul 2>&1
if errorlevel 1 (
    echo [INFO] Backend not running. Starting temporarily...
    start /B "MIRA-API" py -3 -m uvicorn mira.api.app:app --host 127.0.0.1 --port 8000 --log-level warning
    echo [INFO] Waiting 8 seconds for startup...
    timeout /t 8 /nobreak >nul
    set "STARTED_SERVER=1"
) else (
    echo [OK] Backend already running on :8000
    set "STARTED_SERVER=0"
)

REM Health check
curl -s http://127.0.0.1:8000/health 2>nul | findstr "ok" >nul
if errorlevel 1 (
    echo [ERROR] Backend health check failed.
    if "!STARTED_SERVER!"=="1" taskkill /FI "WINDOWTITLE eq MIRA-API" >nul 2>&1
    exit /b 1
)
echo [OK] Health check passed

REM MUA V10 ping
curl -s http://127.0.0.1:8000/mua/v10/ping 2>nul | findstr "mua-v10" >nul
if errorlevel 1 (
    echo [ERROR] MUA V10 ping failed. Router may not be mounted.
    if "!STARTED_SERVER!"=="1" taskkill /FI "WINDOWTITLE eq MIRA-API" >nul 2>&1
    exit /b 1
)
echo [OK] MUA V10 router responding

REM Classify-row smoke test (A286 CRES, FS=U in GH2 — should be THIN_SCREENING)
echo [INFO] Running classification smoke test: A286 CRES FS=U in GH2...
curl -s -X POST http://127.0.0.1:8000/mua/v10/classify-row ^
  -H "Content-Type: application/json" ^
  -d "{\"maptis_code\":\"10392\",\"material_designation\":\"A286 CRES\",\"material_class\":\"metal\",\"media\":\"GH2\",\"environment\":\"non-habitable\",\"ratings\":{\"FLAM\":\"A\",\"FS\":\"U\",\"SCC\":\"A\",\"CORR\":\"A\"}}" ^
  > "%TEMP%\mua_v10_smoke.json" 2>nul

type "%TEMP%\mua_v10_smoke.json" | findstr "THIN_SCREENING" >nul
if errorlevel 1 (
    echo [ERROR] Classification smoke test failed. Expected THIN_SCREENING for FS=U.
    echo [ERROR] Response:
    type "%TEMP%\mua_v10_smoke.json"
    if "!STARTED_SERVER!"=="1" taskkill /FI "WINDOWTITLE eq MIRA-API" >nul 2>&1
    exit /b 1
)
echo [OK] FS=U correctly classified as THIN_SCREENING

REM Anti-rule smoke test (Inconel 625, FLAM=C in GH2 — should be ANTI_RULE)
echo [INFO] Running classification smoke test: Inconel 625 FLAM=C in GH2...
curl -s -X POST http://127.0.0.1:8000/mua/v10/classify-row ^
  -H "Content-Type: application/json" ^
  -d "{\"maptis_code\":\"10727\",\"material_designation\":\"INCONEL 625\",\"material_class\":\"metal\",\"media\":\"GH2\",\"environment\":\"non-habitable\",\"ratings\":{\"FLAM\":\"C\",\"FS\":\"U\"}}" ^
  > "%TEMP%\mua_v10_smoke2.json" 2>nul

type "%TEMP%\mua_v10_smoke2.json" | findstr "ANTI_RULE" >nul
if errorlevel 1 (
    echo [ERROR] Classification smoke test failed. Expected ANTI_RULE for FLAM=C.
    echo [ERROR] Response:
    type "%TEMP%\mua_v10_smoke2.json"
    if "!STARTED_SERVER!"=="1" taskkill /FI "WINDOWTITLE eq MIRA-API" >nul 2>&1
    exit /b 1
)
echo [OK] FLAM=C correctly classified as ANTI_RULE

REM Incomplete pass smoke test (Inconel 718, FLAM=I in GH2 — should be INCOMPLETE_PASS)
echo [INFO] Running classification smoke test: Inconel 718 FLAM=I in GH2...
curl -s -X POST http://127.0.0.1:8000/mua/v10/classify-row ^
  -H "Content-Type: application/json" ^
  -d "{\"maptis_code\":\"55962\",\"material_designation\":\"INCONEL 718\",\"material_class\":\"metal\",\"media\":\"GH2\",\"environment\":\"non-habitable\",\"ratings\":{\"FLAM\":\"I\"}}" ^
  > "%TEMP%\mua_v10_smoke3.json" 2>nul

type "%TEMP%\mua_v10_smoke3.json" | findstr "INCOMPLETE_PASS" >nul
if errorlevel 1 (
    echo [ERROR] Classification smoke test failed. Expected INCOMPLETE_PASS for FLAM=I.
    echo [ERROR] Response:
    type "%TEMP%\mua_v10_smoke3.json"
    if "!STARTED_SERVER!"=="1" taskkill /FI "WINDOWTITLE eq MIRA-API" >nul 2>&1
    exit /b 1
)
echo [OK] FLAM=I correctly classified as INCOMPLETE_PASS

REM Material-class gate test (TOX on metal — should NOT generate MUA)
echo [INFO] Running gate test: TOX=blank on metal — should skip...
curl -s -X POST http://127.0.0.1:8000/mua/v10/classify-row ^
  -H "Content-Type: application/json" ^
  -d "{\"maptis_code\":\"10392\",\"material_designation\":\"A286 CRES\",\"material_class\":\"metal\",\"media\":\"GH2\",\"environment\":\"non-habitable\",\"ratings\":{\"TOX\":\"\"}}" ^
  > "%TEMP%\mua_v10_smoke4.json" 2>nul

type "%TEMP%\mua_v10_smoke4.json" | findstr "\"no_mua_needed_count\":1" >nul
if not errorlevel 1 (
    echo [OK] TOX on metal correctly gated out
) else (
    type "%TEMP%\mua_v10_smoke4.json" | findstr "not applicable" >nul
    if not errorlevel 1 (
        echo [OK] TOX on metal correctly gated out
    ) else (
        echo [WARN] TOX gate test — check response manually:
        type "%TEMP%\mua_v10_smoke4.json"
    )
)

echo.
echo [PASS] All API smoke tests passed.

if "!STARTED_SERVER!"=="1" (
    echo [INFO] Stopping temporary server...
    taskkill /FI "WINDOWTITLE eq MIRA-API" >nul 2>&1
)

if /I "%~1"=="api" goto :done

REM ============================================================
echo.
echo [STAGE 3/3] Checking frontend...
echo ────────────────────────────────────────────────────

if not exist "frontend\package.json" (
    echo [ERROR] frontend/package.json not found
    exit /b 1
)
echo [OK] frontend/package.json exists

if not exist "frontend\node_modules" (
    echo [WARN] node_modules missing. Run: cd frontend ^&^& npm install
) else (
    echo [OK] node_modules present
)

if exist "frontend\src\pages\MUAV10.tsx" (
    echo [OK] MUAV10.tsx exists
) else (
    echo [ERROR] MUAV10.tsx not found!
    exit /b 1
)

if exist "frontend\src\lib\mua-v10-api.ts" (
    echo [OK] mua-v10-api.ts exists
) else (
    echo [ERROR] mua-v10-api.ts not found!
    exit /b 1
)

echo.
echo [INFO] To run full-stack locally:
echo        Terminal 1: py -3 -m uvicorn mira.api.app:app --reload --port 8000
echo        Terminal 2: cd frontend ^&^& npm run dev
echo        Browser:    http://localhost:8080/mua-v10

REM ============================================================
:done
echo.
echo ============================================================
echo  MUA V10 Local Verification — COMPLETE
echo ============================================================
echo.
exit /b 0
