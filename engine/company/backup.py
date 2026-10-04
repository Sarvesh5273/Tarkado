"""Operator-requested private paired backup, without deleting or replacing user files."""

import os
from pathlib import Path
import sqlite3

from django.conf import settings
from django.db import connection

from engine.schemas import ValidationError


def backup_store(destination):
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValidationError("Backup requires a new destination; existing files are never overwritten.")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValidationError("Create a trusted private backup parent directory before requesting this backup.")
    destination.mkdir(mode=0o700)
    database = destination / "company.sqlite3"
    key = destination / ".secret-key"
    # The database contains credential material. Backups are explicit private
    # operator operations, never ordinary metadata exports or automatic Git data.
    with os.fdopen(os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"):
        pass
    connection.ensure_connection()
    with sqlite3.connect(database) as target:
        connection.connection.backup(target)
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise ValidationError("New backup did not pass SQLite integrity checking; preserve it for inspection, not restoration.")
    with os.fdopen(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w") as stream:
        stream.write(settings.SECRET_KEY)
        stream.flush()
        os.fsync(stream.fileno())
    return destination
