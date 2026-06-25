"""Authentication: password hashing and session-based access dependencies.

Login stores the user id in a signed, HttpOnly session cookie (Starlette
``SessionMiddleware``, registered in ``main.py``). Request-time dependencies load
the active user from that session and gate access.
"""

import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from src.database import get_session
from src.models import User

# bcrypt hashes at most the first 72 bytes of a password; truncate explicitly so
# longer inputs fail the same way on hash and verify instead of silently differing.
_MAX_PW_BYTES = 72


def _pw_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_PW_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def current_user(
    request: Request, session: Session = Depends(get_session)
) -> User | None:
    """The logged-in, active user for this request, or None."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = session.get(User, user_id)
    if not user or not user.is_active:
        return None
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    """Gate: 401 unless a valid, active user is logged in."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    """Gate: 403 unless the logged-in user is an admin."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
