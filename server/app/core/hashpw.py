"""CLI helper: generate a bcrypt hash for .env OPSHUB_PASSWORD_HASH.

Usage:
    python -m app.core.hashpw
"""
from __future__ import annotations

import getpass
import sys

from app.core.security import hash_password


def main() -> int:
    pw = getpass.getpass("new password: ")
    pw2 = getpass.getpass("confirm: ")
    if pw != pw2:
        print("mismatch", file=sys.stderr)
        return 1
    if len(pw) < 6:
        print("too short (min 6 chars)", file=sys.stderr)
        return 1
    print()
    print("Add this line to server/.env :")
    print(f'OPSHUB_PASSWORD_HASH={hash_password(pw)}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
