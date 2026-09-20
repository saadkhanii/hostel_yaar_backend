"""Firebase Cloud Messaging sender.

Initializes the Firebase Admin SDK lazily on first use and exposes
`send_push()` for delivering a notification to a single device token.
Failures are logged, never raised — a broken push should not break a
booking flow.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import firebase_admin
from firebase_admin import credentials, messaging

from app.config import settings

logger = logging.getLogger(__name__)

_initialized = False


def _ensure_initialized() -> bool:
    """Initialize the Firebase Admin SDK from env var or file.

    In production, credentials come from FIREBASE_CREDENTIALS_JSON
    (a full JSON string set as an env var on Render). In local dev,
    they come from a file at settings.firebase_credentials_path.

    Returns True if initialized, False otherwise. Logs the reason on
    failure but never raises.
    """
    global _initialized
    if _initialized:
        return True

    raw_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    creds_path = Path(settings.firebase_credentials_path)

    # TEMP DEBUG — remove after this investigation
    logger.warning(
        "FCM DEBUG: raw_json is None = %s, raw_json length = %s",
        raw_json is None,
        len(raw_json) if raw_json else 0,
    )

    try:
        if raw_json:
            cred = credentials.Certificate(json.loads(raw_json))
        elif creds_path.exists():
            cred = credentials.Certificate(str(creds_path))
        else:
            logger.warning(
                "Firebase credentials not found at %s — push notifications disabled",
                creds_path,
            )
            return False

        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        _initialized = True
        logger.info("Firebase Admin SDK initialized")
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

    Silently no-ops if the token is empty or the SDK isn't initialized.
    Never raises.
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