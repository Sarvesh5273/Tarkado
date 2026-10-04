"""Privately save a browser-issued connector credential without editing JSON or activating a plugin."""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from engine.company.runtime import private_directory


def main():
    parser = argparse.ArgumentParser(description="Save an explicitly issued Tarkado credential privately. Does not install/load OpenCode or contact any server.")
    parser.add_argument("--origin", required=True, help="Exact company HTTPS origin or loopback development origin")
    parser.add_argument("--output", required=True, type=Path, help="New file in a trusted private, Git-ignored directory")
    args = parser.parse_args()
    url = urlsplit(args.origin)
    valid = (url.scheme == "https" or url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1"))
    if not valid or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
        parser.error("Use an exact protected HTTPS origin, or explicit loopback development; no credentials/path/query.")
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        parser.error("Existing credential files are never overwritten. Revoke the old pairing and choose a new destination.")
    directory = private_directory(output.parent)
    credential = getpass.getpass("Browser-issued connector credential (hidden, never put in a coding prompt): ")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", credential):
        parser.error("Invalid connector credential shape. No credential was saved or printed.")
    content = json.dumps({"origin": args.origin, "credential": credential}) + "\n"
    with os.fdopen(os.open(directory / output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    print("Private connector file saved. No OpenCode configuration was changed; plugin loading remains an explicit operator action.")


if __name__ == "__main__":
    main()
