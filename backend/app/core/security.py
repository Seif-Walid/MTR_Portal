import secrets

import bcrypt

# Stored for accounts nobody has set a password on yet (members added from the
# roster). Not a bcrypt hash, so no password ever verifies against it.
UNUSABLE_PASSWORD = "!"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)
