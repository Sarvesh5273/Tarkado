"""DEMO-ONLY LiteLLM custom authentication for the full-loop demonstration.

Maps one per-employee gateway key to a stable gateway user ID
("employee-<username>"), which Tarkado's scoped gateway identity maps back to a
company member. Only SHA-256 digests of the keys are stored, in an owner-only
private JSON file named by DEMO_GATEWAY_KEYS. A real company would use its
existing LiteLLM virtual keys or SSO instead.
"""

import hashlib
import hmac
import json
import os
import stat

from fastapi import HTTPException
from litellm.proxy._types import UserAPIKeyAuth


def _digests():
    path = os.environ["DEMO_GATEWAY_KEYS"]
    info = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise HTTPException(status_code=500, detail="DEMO gateway key store is misconfigured.")
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


async def user_api_key_auth(request, api_key):
    if request.url.path not in ("/v1/chat/completions", "/chat/completions"):
        raise HTTPException(status_code=403, detail="Only chat completions are exposed by this DEMO gateway.")
    token = (api_key or "").removeprefix("Bearer ").strip()
    digest = hashlib.sha256(token.encode()).hexdigest()
    for known, user in _digests().items():
        if hmac.compare_digest(known, digest):
            return UserAPIKeyAuth(api_key=digest, user_id=user)
    # HTTPException keeps LiteLLM's auth error path off its (absent) database.
    raise HTTPException(status_code=401, detail="Unknown gateway key.")
