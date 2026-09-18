from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Notification
from app.schemas import NotificationResponse, UnreadCountResponse
from app.utils.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ---------- GET /notifications ----------

@router.get("", response_model=list[NotificationResponse])
def list_notifications(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Current user's notifications, newest first."""
    user_id = current_user["sub"]
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    return rows


# ---------- GET /notifications/unread-count ----------

@router.get("/unread-count", response_model=UnreadCountResponse)
def unread_count(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """How many unread notifications the current user has. Used for
    badge counts in the drawer and alerts tab."""
    user_id = current_user["sub"]
    count = (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        .count()
    )
    return UnreadCountResponse(count=count)


# ---------- PATCH /notifications/read-all  (must be BEFORE /{id}/read) ----------

@router.patch("/read-all", status_code=status.HTTP_200_OK)
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["sub"]
    (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
        .update({Notification.is_read: True})
    )
    db.commit()
    return {"status": "ok"}


# ---------- PATCH /notifications/{id}/read ----------

@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
)
def mark_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["sub"]
    row = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    row.is_read = True
    db.commit()
    db.refresh(row)
    return row