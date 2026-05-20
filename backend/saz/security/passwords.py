"""Password hashing utilities.

Uses bcrypt directly (the same primitive ``passlib[bcrypt]`` would call).
Cost factor 12 keeps verification under ~250ms on typical hardware while
remaining strong enough for production user passwords.
"""

import bcrypt

_BCRYPT_ROUNDS = 12
# bcrypt silently truncates inputs longer than 72 bytes, which is a footgun
# (a 73-char password and a 100-char password with the same prefix would
# hash identically). Reject longer inputs at the boundary instead.
_MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt.

    Returns a self-contained hash string (algorithm + cost + salt + digest)
    suitable for storing directly in the ``users.password_hash`` column.
    """
    if not isinstance(plain, str):
        raise TypeError("password must be a string")
    encoded = plain.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        raise ValueError(f"password too long: bcrypt accepts at most {_MAX_PASSWORD_BYTES} bytes")
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(encoded, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time compare of a plaintext password against a stored hash.

    Returns False on any mismatch or malformed hash — never raises, so
    callers can use it as a boolean gate without try/except. Passwords
    over the bcrypt limit are rejected here just like at hashing time, so
    a 100-char attempt cannot match a hash created from a 72-char prefix.
    """
    if not plain or not hashed:
        return False
    encoded = plain.encode("utf-8")
    if len(encoded) > _MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
