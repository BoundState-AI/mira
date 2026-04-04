#!/usr/bin/env bash
set -euo pipefail

ROOT="/mnt/d/BoundState"
MIRA_ROOT="$ROOT/boundstate_mira"
FORGE_ROOT="$ROOT/boundstate_forge"

echo "[1/6] Python compile checks"
python3 -m py_compile \
  "$MIRA_ROOT/unified/schema.py" \
  "$MIRA_ROOT/unified/canonical_store.py" \
  "$MIRA_ROOT/unified/compiler.py" \
  "$MIRA_ROOT/unified/chat/routes.py" \
  "$MIRA_ROOT/unified/forge_contract_adapter.py" \
  "$MIRA_ROOT/unified/pipeline/pipeline.py" \
  "$FORGE_ROOT/standalone_forge/ic_proxy.py" \
  "$FORGE_ROOT/standalone_forge/uploads.py" \
  "$FORGE_ROOT/standalone_forge/app.py"

echo "[2/6] MIRA FORGE-IC regression subset"
PYTHONPATH="$MIRA_ROOT" pytest -s \
  "$MIRA_ROOT/unified/tests/test_compiler.py" \
  "$MIRA_ROOT/unified/tests/test_chat_routes.py" \
  "$MIRA_ROOT/unified/tests/test_canonical_store.py" \
  "$MIRA_ROOT/unified/tests/test_forge_contract_adapter.py" \
  "$MIRA_ROOT/unified/tests/test_unified_pipeline.py"

echo "[3/6] FORGE proxy/upload integration subset"
PYTHONPATH="$MIRA_ROOT:$FORGE_ROOT" pytest -s \
  "$FORGE_ROOT/tests/test_upload_routes.py" \
  "$FORGE_ROOT/tests/test_ic_proxy_integration.py"

echo "[4/6] Frontend production build"
(
  cd "$FORGE_ROOT/frontend"
  npm run build
)

echo "[5/6] Legacy endpoint consumer review"
rg -n "(/api/ic/chat/query|/api/ic/capabilities|/ic/chat/query|/ic/capabilities)" \
  "$FORGE_ROOT" "$MIRA_ROOT" \
  -g '!**/__pycache__/**'

echo "[6/6] Gate complete"
