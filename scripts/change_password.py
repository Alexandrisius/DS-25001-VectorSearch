"""Change admin password — generate bcrypt hash, update .env, restart API.

Usage:
    python scripts/change_password.py NEW_PASSWORD

Or:
    python scripts/change_password.py           # interactive prompt
"""
from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

import bcrypt


def generate_hash(password: str) -> str:
    """Generate bcrypt hash for the given password."""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def escape_for_docker(value: str) -> str:
    """Escape $ as $$ for Docker Compose .env files."""
    return value.replace("$", "$$")


def update_env_file(env_path: Path, new_hash: str) -> bool:
    """Update ADMIN_PASSWORD_HASH in .env file. Returns True if changed."""
    if not env_path.exists():
        print(f"ERROR: {env_path} not found")
        return False

    content = env_path.read_text(encoding="utf-8")
    # Match ADMIN_PASSWORD_HASH=... (any value, possibly with $$ escapes)
    pattern = re.compile(r"^ADMIN_PASSWORD_HASH=.*$", re.MULTILINE)
    match = pattern.search(content)
    if not match:
        print(f"ERROR: ADMIN_PASSWORD_HASH not found in {env_path}")
        print("Add this line:")
        print(f"ADMIN_PASSWORD_HASH={escape_for_docker(new_hash)}")
        return False

    old_line = match.group(0)
    new_line = f"ADMIN_PASSWORD_HASH={escape_for_docker(new_hash)}"
    new_content = content.replace(old_line, new_line)
    env_path.write_text(new_content, encoding="utf-8")
    return True


def main() -> int:
    # Get password from args or prompt
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("New admin password: ")
        if not password:
            print("ERROR: password cannot be empty")
            return 1
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("ERROR: passwords do not match")
            return 1

    if len(password) < 4:
        print("ERROR: password too short (min 4 chars)")
        return 1

    # Generate hash
    print("Generating bcrypt hash...")
    new_hash = generate_hash(password)
    escaped = escape_for_docker(new_hash)
    print(f"Hash: {new_hash[:30]}...")
    print(f"Escaped (for Docker): {escaped[:30]}...")

    # Update .env
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not update_env_file(env_path, new_hash):
        return 1
    print(f"[OK] Updated {env_path}")

    # Verification
    if bcrypt.checkpw(password.encode("utf-8"), new_hash.encode("utf-8")):
        print("[OK] Hash verified")
    else:
        print("[ERROR] Hash verification FAILED")
        return 1

    print("")
    print("Now restart API to apply the new password:")
    print("  make rebuild-api")
    print("")
    print("Or just use make password (it will do everything):")
    print(f"  make password NEW='{password}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
