"""Export a versioned local proposal, not an approved live configuration."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, List

from .privacy import ensure_safe
from .schemas import Policy


def _write_private(content: str, path: Path) -> None:
    ensure_safe(str(path))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".export-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Linking a completed temporary file publishes the export without replacing anything.
        os.link(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def export_jsonl(records: List[Any], path: Path) -> None:
    ensure_safe(records)
    content = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records)
    _write_private(content, path)


def export_policy(policy: Policy, path: Path) -> None:
    # Validate before touching the destination and never overwrite an existing file.
    validated = Policy.from_dict(policy.to_dict())
    ensure_safe(validated.to_dict())
    content = json.dumps(validated.to_dict(), indent=2, ensure_ascii=False) + "\n"
    _write_private(content, path)
