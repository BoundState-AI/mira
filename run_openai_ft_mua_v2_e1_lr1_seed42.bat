@echo off
setlocal

REM Run from this BAT file's directory (repo root expected)
cd /d "%~dp0"

set "TRAIN_FILE=%CD%\mua_rationale_train_v2_curated.jsonl"
set "VAL_FILE=%CD%\mua_rationale_val_v2_curated.jsonl"
set "MODEL=gpt-4.1-2025-04-14"
set "SEED=42"
set "SUFFIX=mua-rat-v2-e1-lr1"

if not exist "%TRAIN_FILE%" (
  echo ERROR: Missing training file:
  echo   %TRAIN_FILE%
  exit /b 1
)

if not exist "%VAL_FILE%" (
  echo ERROR: Missing validation file:
  echo   %VAL_FILE%
  exit /b 1
)

if "%OPENAI_API_KEY%"=="" (
  echo OPENAI_API_KEY is not set.
  set /p OPENAI_API_KEY=Paste OPENAI_API_KEY and press Enter: 
)

echo.
echo Launching OpenAI fine-tune:
echo   Train: %TRAIN_FILE%
echo   Val:   %VAL_FILE%
echo   Model: %MODEL%
echo   Seed:  %SEED%
echo   Epochs: 1
echo   LR multiplier: 1.0
echo.

python -u scripts\openai_ft_launch.py ^
  --train-file "%TRAIN_FILE%" ^
  --val-file "%VAL_FILE%" ^
  --model "%MODEL%" ^
  --seed %SEED% ^
  --n-epochs 1 ^
  --batch-size auto ^
  --learning-rate-multiplier 1.0 ^
  --suffix "%SUFFIX%" ^
  --wait ^
  --poll-seconds 30

set "EXITCODE=%ERRORLEVEL%"
echo.
echo Done. Exit code: %EXITCODE%
exit /b %EXITCODE%

