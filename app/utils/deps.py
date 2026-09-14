from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.utils.security import decode_access_token

bearer_scheme = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    """
    Use this on any future route that needs a logged-in user, e.g.:

        @router.get("/profile")
        def get_profile(current_user: dict = Depends(get_current_user)):
            ...

    The Flutter app sends: Authorization: Bearer <token>
    This verifies the signature (no DB lookup needed) and returns the payload.
    """
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload
