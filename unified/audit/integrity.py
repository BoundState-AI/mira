from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from unified.canonical_store import CanonicalStore


class AuditIntegrityService:
    def __init__(self, signer: Callable[[str], str] | None = None) -> None:
        self._signer = signer

    def verify(
        self,
        store: CanonicalStore,
        version: str = "0.1.0",
        domain_pack_hash: str = "",
    ) -> dict[str, Any]:
        verification = store.verify_audit_integrity()
        cached = store.audit_status()
        manifest = {
            "root_hash": cached.get("root_hash", ""),
            "record_count": cached.get("record_count", 0),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "ic_version": version,
            "domain_pack_hash": domain_pack_hash,
        }
        payload = json.dumps(manifest, sort_keys=True)
        signature = self._signer(payload) if self._signer else hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return {
            **verification,
            "manifest": manifest,
            "signature": signature,
            "signing_method": "custom" if self._signer else "sha256",
        }
