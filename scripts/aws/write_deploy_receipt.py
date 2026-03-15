#!/usr/bin/env python3
"""Write a structured deploy receipt for the GovCloud runtime."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: str | None) -> Any:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-dir", required=True)
    parser.add_argument("--deploy-ref", required=True)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--backend-task-def", required=True)
    parser.add_argument("--frontend-task-def", required=True)
    parser.add_argument("--preflight-passed", default="true")
    parser.add_argument("--predeploy-json")
    parser.add_argument("--public-smoke-json")
    parser.add_argument("--auth-smoke-json")
    parser.add_argument("--audit-log")
    args = parser.parse_args()

    receipt_dir = Path(args.receipt_dir).resolve()
    receipt_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    filename = f"deploy-receipt-{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    receipt_path = receipt_dir / filename

    payload = {
        "timestamp_utc": timestamp.isoformat(),
        "deploy_ref": args.deploy_ref,
        "image_tag": args.image_tag,
        "base_url": args.base_url,
        "images": {
            "backend": args.backend_image,
            "frontend": args.frontend_image,
        },
        "task_definitions": {
            "backend": args.backend_task_def,
            "frontend": args.frontend_task_def,
        },
        "preflight_passed": args.preflight_passed.strip().lower() in {"1", "true", "yes"},
        "predeploy_checks": _read_json(args.predeploy_json),
        "public_smoke": _read_json(args.public_smoke_json),
        "authenticated_smoke": _read_json(args.auth_smoke_json),
        "audit_log": str(Path(args.audit_log).resolve()) if args.audit_log else None,
    }
    receipt_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(receipt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
