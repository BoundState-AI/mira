@echo off
REM BoundState MIRA - Local Development Startup (Windows)
REM Run this from the project root (e.g., C:\BoundState)

echo ============================================
echo   BoundState MIRA - Local Dev Environment
echo ============================================
echo.

REM Check for Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found. Install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

REM Check for Node
node --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Node.js not found. Install Node.js 18+ from https://nodejs.org
    pause
    exit /b 1
)

echo [1/4] Installing frontend dependencies...
call npm install

echo.
echo [2/4] Installing backend dependencies...
cd backend
pip install -r requirements.txt
cd ..

echo.
echo [3/4] Starting backend on http://localhost:8000 ...
start "MIRA Backend" cmd /k "cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

echo.
echo [4/4] Starting frontend on http://localhost:8080 ...
timeout /t 3 /nobreak >nul
start "MIRA Frontend" cmd /k "npm run dev"

echo.
echo ============================================
echo   Both servers starting in separate windows
echo   Frontend: http://localhost:8080
echo   Backend:  http://localhost:8000
echo   API Docs: http://localhost:8000/docs
echo ============================================
echo.
pause
