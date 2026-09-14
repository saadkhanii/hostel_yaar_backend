from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.config import settings


class InvalidGoogleTokenError(Exception):
    pass


def verify_google_id_token(token: str) -> dict:
    """
    This is the step where WE act as the verifier (the role Google's OAuth
    server played in the FCM example). The Flutter app already did the
    "sign in with Google" dance and got back an ID token signed by GOOGLE's
    private key. Here we check that signature using Google's public keys
    (fetched automatically by this library), confirming:
      1. It was really signed by Google
      2. It was issued for OUR app (matches google_client_id)
      3. It hasn't expired

    Returns the verified payload: {"sub": google_user_id, "email": ..., "name": ..., ...}
    """
    try:
        payload = id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.google_client_id
        )
    except ValueError as e:
        raise InvalidGoogleTokenError(str(e))

    if payload.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise InvalidGoogleTokenError("Invalid issuer")

    return payload
