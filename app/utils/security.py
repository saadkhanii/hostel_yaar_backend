from datetime import datetime, timedelta
import secrets

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(*, user_id: str, email: str, role: str) -> str:
    """
    This is the JWT we discussed: signed with our own secret key
    (jwt_secret_key), carrying just enough info to identify the user
    on future requests without a database lookup every time.
    """
    expire = datetime.utcnow() + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    """Returns the payload if the token is valid and not expired/tampered, else None."""
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None



def generate_refresh_token() -> str:
    """Generate a cryptographically random, URL-safe refresh token.

    64 bytes of entropy, base64-url encoded — long enough that guessing
    is infeasible.
    """
    return secrets.token_urlsafe(64)


def refresh_token_expiry() -> datetime:
    """When a freshly-issued refresh token should expire."""
    from app.config import settings

    return datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
