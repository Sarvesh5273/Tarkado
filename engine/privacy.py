"""Conservative metadata checks, not a guarantee that data contains no secrets."""

import re
import math
from decimal import Decimal
from typing import Any, Tuple


class PrivacyError(ValueError):
    """Metadata is unsafe to print or persist. Never include the matched value."""


SECRET_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("private_key", re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----.*?"
        r"(?:-----END (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|$)", re.DOTALL)),
    ("provider_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("cloud_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google_key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*", re.IGNORECASE)),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("credential_assignment", re.compile(
        r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|password|passwd|secret|client[_ -]?secret|authorization|private[_ -]?key)"
        r"\b[\"']?\s*[:=]\s*(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;\"']+)", re.IGNORECASE)),
    ("credential_flag", re.compile(
        r"--(?:api[-_]key|access[-_]token|password|passwd|secret|token|authorization)(?:=|\s+)"
        r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s]+)", re.IGNORECASE)),
    ("url_credentials", re.compile(r"https?://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)),
    ("url_secret_query", re.compile(
        r"[?&](?:api_key|access_token|token|key|secret|password)=[^\s&#]+", re.IGNORECASE)),
)
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")
SECRET_FIELDS = {"apikey", "accesstoken", "refreshtoken", "token", "password", "passwd",
                 "clientsecret", "secret", "authorization", "privatekey"}


def ensure_safe(value: Any) -> None:
    if isinstance(value, str):
        if any(pattern.search(value) for _, pattern in SECRET_PATTERNS):
            raise PrivacyError("Potential secret detected; input/output refused. Sensitive values are not shown.")
        if CONTROL_CHARACTERS.search(value):
            raise PrivacyError("Control characters or multiline metadata are not supported.")
        if len(value) > 1024:
            raise PrivacyError("Metadata strings must be at most 1024 characters; raw content is unsupported.")
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PrivacyError("Metadata object keys must be strings.")
            ensure_safe(key)
            normalized = re.sub(r"[^a-z]", "", key.lower())
            empty = item is None or (isinstance(item, str) and item == "")
            if normalized in SECRET_FIELDS and not empty:
                raise PrivacyError("Credential fields are not accepted as metadata; input/output refused.")
            ensure_safe(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            ensure_safe(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise PrivacyError("Non-finite metadata numbers cannot be exported.")
    elif isinstance(value, Decimal) and not value.is_finite():
        raise PrivacyError("Non-finite metadata numbers cannot be exported.")
    elif value is not None and not isinstance(value, (bool, int, float, Decimal)):
        raise PrivacyError("Unsupported metadata type; serialization refused.")


def redact_text(value: str) -> str:
    # Redaction is for diagnostics only. Routing inputs must never be silently changed.
    for _, pattern in SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return CONTROL_CHARACTERS.sub(" ", value)
