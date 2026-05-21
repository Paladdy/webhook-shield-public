import hashlib
import hmac
import json
from typing import Any


def compute_hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def signature_candidates(raw_body: bytes, parsed: dict[str, Any] | None) -> list[bytes]:
    candidates = [raw_body]
    if parsed is not None:
        candidates.append(
            json.dumps(parsed, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
    return candidates


def verify_hmac_signature(
    secret: str,
    raw_body: bytes,
    signature: str | None,
    parsed: dict[str, Any] | None,
) -> bool:
    if not signature:
        return False
    expected_sig = signature.strip().lower()
    for message in signature_candidates(raw_body, parsed):
        computed = compute_hmac_hex(secret, message)
        if hmac.compare_digest(computed, expected_sig):
            return True
    return False
