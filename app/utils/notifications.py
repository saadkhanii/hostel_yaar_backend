"""Helpers for creating notifications from other routers.

These are plain sync functions that take a Session and add a row. Callers
are responsible for committing the session. Keeping them here (rather
than as a service class) matches the rest of the project's utility style.
"""

from sqlalchemy.orm import Session

from app.models import Notification, NotificationType


def notify_warden_booking_created(
    db: Session,
    *,
    warden_id: str,
    seeker_name: str,
    hostel_name: str,
    room_number: str,
    booking_id: str,
) -> None:
    """Called when a seeker creates a booking request."""
    db.add(
        Notification(
            user_id=warden_id,
            type=NotificationType.booking_created,
            title="New booking request",
            body=f"{seeker_name} requested Room {room_number} at {hostel_name}.",
            related_id=booking_id,
        )
    )


def notify_seeker_booking_accepted(
    db: Session,
    *,
    seeker_id: str,
    hostel_name: str,
    room_number: str,
    booking_id: str,
) -> None:
    """Called when a warden accepts a booking request."""
    db.add(
        Notification(
            user_id=seeker_id,
            type=NotificationType.booking_accepted,
            title="Request accepted",
            body=f"Your request for Room {room_number} at {hostel_name} was accepted.",
            related_id=booking_id,
        )
    )


def notify_seeker_booking_rejected(
    db: Session,
    *,
    seeker_id: str,
    hostel_name: str,
    room_number: str,
    booking_id: str,
) -> None:
    """Called when a warden rejects a booking request."""
    db.add(
        Notification(
            user_id=seeker_id,
            type=NotificationType.booking_rejected,
            title="Request rejected",
            body=f"Your request for Room {room_number} at {hostel_name} was not accepted.",
            related_id=booking_id,
        )
    )

def notify_warden_booking_cancelled(
    db: Session,
    *,
    warden_id: str,
    seeker_name: str,
    hostel_name: str,
    room_number: str,
    booking_id: str,
) -> None:
    """Called when a seeker cancels their pending request."""
    db.add(
        Notification(
            user_id=warden_id,
            type=NotificationType.booking_cancelled,
            title="Booking request cancelled",
            body=f"{seeker_name} cancelled their request for Room {room_number} at {hostel_name}.",
            related_id=booking_id,
        )
    )