"""Firebase Cloud Messaging sender.

Initializes the Firebase Admin SDK once at import time (lazily) and
provides a simple `send_push()` that delivers a notification to a
single device token.
"""

import logging
from pathlib import Path
from typing import Optional

import firebase_admin
from firebase_admin import credentials, messaging

from app.config import settings

logger = logging.getLogger(__name__)

# Initialize lazily — only the first call actually sets up the SDK.
_initialized = False


def _ensure_initialized() -> bool:
    """Initialize the Firebase Admin SDK from the service account file.

    Returns True if initialization succeeded (or was already done),
    False otherwise. Failures are logged but not raised — a push
    notification is a nice-to-have, not a critical path.
    """
    global _initialized
    if _initialized:
        return True

    creds_path = Path(settings.firebase_credentials_path)
    if not creds_path.exists():
        logger.warning(
            "Firebase credentials not found at %s — push notifications disabled",
            creds_path,
        )
        return False

    try:
        cred = credentials.Certificate(str(creds_path))
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        _initialized = True
        return True
    except Exception:
        logger.exception("Failed to initialize Firebase Admin SDK")
        return False


def send_push(
    *,
    token: Optional[str],
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> None:
    """Send a push notification to a single FCM token.

    Silently does nothing if the token is empty or the SDK isn't
    initialized. Errors are logged, not raised.
    """
    if not token:
        return
    if not _ensure_initialized():
        return

    try:
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    sound="default",
                    channel_id="hostel_yaar_default",
                ),
            ),
        )
        messaging.send(message)
        logger.info("Push sent to %s...", token[:20])
    except Exception:
        logger.exception("Failed to send push notification")