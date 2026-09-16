from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Hostel, SavedHostel, UserRole
from app.utils.deps import get_current_user

router = APIRouter(prefix="/saved-hostels", tags=["saved-hostels"])


def _require_seeker(current_user: dict) -> str:
    """Only seekers can save hostels. Returns the user's id."""
    if current_user.get("role") != UserRole.seeker.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only seekers can save hostels",
        )
    return current_user["sub"]


def _hostel_summary_dict(hostel: Hostel) -> dict:
    """Shape a Hostel ORM object into the same JSON shape HostelSummary
    produces in hostels.py, including the computed fields."""
    starting_price = (
        min(room.price for room in hostel.rooms) if hostel.rooms else 0
    )
    has_vacancy = any(
        (
            room.available_seats > 0
            if room.booking_type.value == "Seat"
            else room.vacant
        )
        for room in hostel.rooms
    )
    return {
        "id": hostel.id,
        "warden_id": hostel.warden_id,
        "name": hostel.name,
        "city": hostel.city,
        "address": hostel.address,
        "type": hostel.type.value,
        "latitude": hostel.latitude,
        "longitude": hostel.longitude,
        "facilities": hostel.facilities,
        "photos": hostel.photos,
        "phone": hostel.phone,
        "whatsapp": hostel.whatsapp,
        "in_app_chat": hostel.in_app_chat,
        "active": hostel.active,
        "starting_price": starting_price,
        "has_vacancy": has_vacancy,
        "room_count": len(hostel.rooms),
        "created_at": hostel.created_at.isoformat(),
        "updated_at": hostel.updated_at.isoformat(),
    }


# ---------- GET /saved-hostels ----------

@router.get("")
def list_saved_hostels(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return the current seeker's saved hostels, most recent first,
    each as { saved_at, hostel }."""
    user_id = _require_seeker(current_user)

    rows = (
        db.query(SavedHostel)
        .options(joinedload(SavedHostel.hostel).joinedload(Hostel.rooms))
        .filter(SavedHostel.user_id == user_id)
        .order_by(SavedHostel.created_at.desc())
        .all()
    )

    return [
        {
            "saved_at": row.created_at.isoformat(),
            "hostel": _hostel_summary_dict(row.hostel),
        }
        for row in rows
    ]


# ---------- POST /saved-hostels/{hostel_id} ----------

@router.post("/{hostel_id}", status_code=status.HTTP_201_CREATED)
def save_hostel(
    hostel_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Save a hostel. Idempotent — saving an already-saved hostel is a
    no-op and returns success."""
    user_id = _require_seeker(current_user)

    hostel = db.query(Hostel).filter(Hostel.id == hostel_id).first()
    if hostel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hostel not found",
        )

    existing = (
        db.query(SavedHostel)
        .filter(
            SavedHostel.user_id == user_id,
            SavedHostel.hostel_id == hostel_id,
        )
        .first()
    )
    if existing is not None:
        return {"status": "already saved"}

    db.add(SavedHostel(user_id=user_id, hostel_id=hostel_id))
    db.commit()
    return {"status": "saved"}


# ---------- DELETE /saved-hostels/{hostel_id} ----------

@router.delete("/{hostel_id}", status_code=status.HTTP_204_NO_CONTENT)
def unsave_hostel(
    hostel_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Remove a saved hostel. Idempotent — unsaving something that isn't
    saved is a no-op and returns success."""
    user_id = _require_seeker(current_user)

    row = (
        db.query(SavedHostel)
        .filter(
            SavedHostel.user_id == user_id,
            SavedHostel.hostel_id == hostel_id,
        )
        .first()
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return None