from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Hostel, HostelType, Room, User, UserRole
from app.schemas import (
    HostelCreate,
    HostelDetail,
    HostelSummary,
    HostelUpdate,
    RoomCreate,
    RoomResponse,
    RoomUpdate,
)
from app.utils.deps import get_current_user

router = APIRouter(prefix="/hostels", tags=["hostels"])


# ---------- helpers ----------

def _require_warden(current_user: dict) -> str:
    """Every hostel mutation is warden-only. Returns the warden's user_id."""
    if current_user.get("role") != UserRole.warden.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only wardens can manage hostels",
        )
    return current_user["sub"]


def _get_hostel_or_404(db: Session, hostel_id: str) -> Hostel:
    hostel = (
        db.query(Hostel)
        .options(joinedload(Hostel.rooms))
        .filter(Hostel.id == hostel_id)
        .first()
    )
    if hostel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hostel not found",
        )
    return hostel


def _assert_owner(hostel: Hostel, warden_id: str) -> None:
    if hostel.warden_id != warden_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this hostel",
        )


def _starting_price(hostel: Hostel) -> int:
    """Cheapest room's monthly rent, or 0 if the hostel has no rooms.

    The ORM object doesn't have this field — HostelSummary declares it
    but the router must supply a value. FastAPI's from_attributes path
    will pick this up if we attach it before serialization.
    """
    if not hostel.rooms:
        return 0
    return min(room.price for room in hostel.rooms)


def _room_fields(payload: RoomCreate) -> dict:
    """Convert a RoomCreate schema into model kwargs, keeping the field
    mapping in one place so add-room and update-room stay in sync."""
    return {
        "number": payload.number,
        "booking_type": payload.booking_type,
        "room_type": payload.room_type,
        "available_seats": payload.available_seats,
        "attached_washroom": payload.attached_washroom,
        "price": payload.price,
        "advance": payload.advance,
        "vacant": payload.vacant,
        "availability_dates": payload.availability_dates,
    }


# ---------- POST /hostels  (add_hostel.dart) ----------

@router.post("", response_model=HostelDetail, status_code=status.HTTP_201_CREATED)
def create_hostel(
    payload: HostelCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warden_id = _require_warden(current_user)

    hostel = Hostel(
        warden_id=warden_id,
        name=payload.name,
        city=payload.city,
        address=payload.address,
        type=payload.type,
        latitude=payload.latitude,
        longitude=payload.longitude,
        facilities=payload.facilities,
        photos=payload.photos,
        phone=payload.phone,
        whatsapp=payload.whatsapp,
        in_app_chat=payload.in_app_chat,
        active=payload.active,
    )
    db.add(hostel)
    db.flush()  # assign hostel.id before creating rooms

    for room_payload in payload.rooms:
        db.add(Room(hostel_id=hostel.id, **_room_fields(room_payload)))

    db.commit()
    db.refresh(hostel)
    # Attach computed field so HostelDetail serialization includes it.
    hostel.starting_price = _starting_price(hostel)
    return hostel


# ---------- GET /hostels  (hostel_list.dart, seeker_dashboard.dart) ----------

@router.get("", response_model=list[HostelSummary])
def list_hostels(
    db: Session = Depends(get_db),
    city: Optional[str] = Query(default=None),
    type: Optional[HostelType] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Search by name"),
    include_inactive: bool = Query(default=False),
):
    """Public listing. Filters are all optional. Inactive hostels are
    hidden by default so a warden can draft a listing without it
    appearing in searches."""
    query = db.query(Hostel).options(joinedload(Hostel.rooms))

    if not include_inactive:
        query = query.filter(Hostel.active.is_(True))

    if city:
        query = query.filter(Hostel.city.ilike(f"%{city}%"))
    if type:
        query = query.filter(Hostel.type == type)
    if q:
        query = query.filter(Hostel.name.ilike(f"%{q}%"))

    hostels = query.order_by(Hostel.created_at.desc()).all()
    for h in hostels:
        h.starting_price = _starting_price(h)
    return hostels


# ---------- GET /hostels/mine  (manage_hostels.dart) ----------

@router.get("/mine", response_model=list[HostelDetail])
def list_my_hostels(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Returns the logged-in warden's own hostels, including inactive
    ones, with rooms loaded. This is what Manage Hostels shows."""
    warden_id = _require_warden(current_user)
    hostels = (
        db.query(Hostel)
        .options(joinedload(Hostel.rooms))
        .filter(Hostel.warden_id == warden_id)
        .order_by(Hostel.created_at.desc())
        .all()
    )
    for h in hostels:
        h.starting_price = _starting_price(h)
    return hostels


# ---------- GET /hostels/{hostel_id}  (hostel_detail.dart) ----------

@router.get("/{hostel_id}", response_model=HostelDetail)
def get_hostel(hostel_id: str, db: Session = Depends(get_db)):
    hostel = _get_hostel_or_404(db, hostel_id)
    hostel.starting_price = _starting_price(hostel)
    return hostel


# ---------- PUT /hostels/{hostel_id}  (edit_hostel_screen.dart) ----------

@router.put("/{hostel_id}", response_model=HostelDetail)
def update_hostel(
    hostel_id: str,
    payload: HostelUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warden_id = _require_warden(current_user)
    hostel = _get_hostel_or_404(db, hostel_id)
    _assert_owner(hostel, warden_id)

    # Only overwrite fields the client actually sent (exclude_unset
    # makes this work — Pydantic tells us which fields were provided).
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(hostel, field, value)

    db.commit()
    db.refresh(hostel)
    hostel.starting_price = _starting_price(hostel)
    return hostel


# ---------- DELETE /hostels/{hostel_id}  (manage_hostels.dart) ----------

@router.delete("/{hostel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hostel(
    hostel_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warden_id = _require_warden(current_user)
    hostel = _get_hostel_or_404(db, hostel_id)
    _assert_owner(hostel, warden_id)

    db.delete(hostel)
    db.commit()
    return None


# ---------- POST /hostels/{hostel_id}/rooms  (add room to existing hostel) ----------

@router.post(
    "/{hostel_id}/rooms",
    response_model=RoomResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_room(
    hostel_id: str,
    payload: RoomCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warden_id = _require_warden(current_user)
    hostel = _get_hostel_or_404(db, hostel_id)
    _assert_owner(hostel, warden_id)

    # Prevent duplicate room numbers within the same hostel.
    existing = (
        db.query(Room)
        .filter(Room.hostel_id == hostel.id, Room.number == payload.number)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Room "{payload.number}" already exists in this hostel',
        )

    room = Room(hostel_id=hostel.id, **_room_fields(payload))
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


# ---------- PUT /hostels/{hostel_id}/rooms/{room_id}  (hostel_rooms_screen.dart) ----------

@router.put("/{hostel_id}/rooms/{room_id}", response_model=RoomResponse)
def update_room(
    hostel_id: str,
    room_id: str,
    payload: RoomUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warden_id = _require_warden(current_user)
    hostel = _get_hostel_or_404(db, hostel_id)
    _assert_owner(hostel, warden_id)

    room = (
        db.query(Room)
        .filter(Room.id == room_id, Room.hostel_id == hostel.id)
        .first()
    )
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found in this hostel",
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)

    db.commit()
    db.refresh(room)
    return room


# ---------- DELETE /hostels/{hostel_id}/rooms/{room_id} ----------

@router.delete(
    "/{hostel_id}/rooms/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_room(
    hostel_id: str,
    room_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warden_id = _require_warden(current_user)
    hostel = _get_hostel_or_404(db, hostel_id)
    _assert_owner(hostel, warden_id)

    room = (
        db.query(Room)
        .filter(Room.id == room_id, Room.hostel_id == hostel.id)
        .first()
    )
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found in this hostel",
        )

    db.delete(room)
    db.commit()
    return None