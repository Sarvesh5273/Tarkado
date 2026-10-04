"""Small explicit private startup files, never credential discovery or repair."""

import os
import stat
from pathlib import Path

from engine.importers import parse_json
from engine.schemas import ValidationError


def private_json(path, limit=16384):
    path = Path(path)
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > limit:
                raise ValidationError("Startup configuration must be a bounded owner-only regular file.")
            content = stream.read(limit + 1)
            if len(content) > limit:
                raise ValidationError("Startup configuration exceeds its explicit bound.")
        return parse_json(content.decode("utf-8"))
    except (OSError, UnicodeError):
        raise ValidationError("Private startup configuration is unreadable; no files or permissions were changed.") from None
