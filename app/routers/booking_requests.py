from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import (
    BookingRequest,
    BookingStatus,
    Hostel,
    Room,
    UserRole,
)
from app.schemas import (
    BookingRequestCreate,
    BookingRequestResponse,
    BookingRequestWardenAction,
)
from app.utils.deps import get_current_user

router = APIRouter(prefix="/booking-requests", tags=["booking-requests"])


# ---------- helpers ----------

def _require_seeker(current_user: dict) -> str:
    if current_user.get("role") != UserRole.seeker.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only seekers can create booking requests",
        )
    return current_user["sub"]


def _require_warden(current_user: dict) -> str:
    if current_user.get("role") != UserRole.warden.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only wardens can respond to booking requests",
        )
    return current_user["sub"]


def _to_response(req: BookingRequest) -> BookingRequestResponse:
    """Flatten a BookingRequest + its relations into the response shape."""
    return BookingRequestResponse(
        id=req.id,
        seeker_id=req.seeker_id,
        hostel_id=req.hostel_id,
        room_id=req.room_id,
        move_in_date=req.move_in_date,
        message=req.message,
        warden_reply=req.warden_reply,
        status=req.status,
        created_at=req.created_at,
        responded_at=req.responded_at,
        seeker_name=req.seeker.full_name if req.seeker else "",
        seeker_phone=None,  # we don't store phone on users yet
        hostel_name=req.hostel.name if req.hostel else "",
        hostel_city=req.hostel.city if req.hostel else "",
        room_number=req.room.number if req.room else "",
        room_type=req.room.room_type if req.room else 0,
        room_booking_type=req.room.booking_type.value if req.room else "",
        room_price=req.room.price if req.room else 0,
        room_advance=req.room.advance if req.room else 0,
    )


def _base_query(db: Session):
    """Eager-load everything we need for the response, so we don't fire
    N+1 queries when listing."""
    return db.query(BookingRequest).options(
        joinedload(BookingRequest.seeker),
        joinedload(BookingRequest.hostel),
        joinedload(BookingRequest.room),
    )


# ---------- POST /booking-requests  (hostel_detail.dart) ----------

@router.post("", response_model=BookingRequestResponse, status_code=status.HTTP_201_CREATED)
def create_booking_request(
    payload: BookingRequestCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    seeker_id = _require_seeker(current_user)

    # Validate the hostel + room exist and the room belongs to the hostel.
    room = db.query(Room).filter(Room.id == payload.room_id).first()
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )
    if room.hostel_id != payload.hostel_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Room does not belong to this hostel",
        )

    hostel = db.query(Hostel).filter(Hostel.id == payload.hostel_id).first()
    if hostel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hostel not found",
        )
    if not hostel.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This hostel is not currently accepting requests",
        )

    # One pending request per room per seeker.
    existing = (
        db.query(BookingRequest)
        .filter(
            BookingRequest.seeker_id == seeker_id,
            BookingRequest.room_id == payload.room_id,
            BookingRequest.status == BookingStatus.pending,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have a pending request for this room",
        )

    req = BookingRequest(
        seeker_id=seeker_id,
        hostel_id=payload.hostel_id,
        room_id=payload.room_id,
        move_in_date=payload.move_in_date,
        message=payload.message,
        status=BookingStatus.pending,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Reload with eager relations for the response.
    req = _base_query(db).filter(BookingRequest.id == req.id).first()
    return _to_response(req)


# ---------- GET /booking-requests/mine  (seeker side) ----------

@router.get("/mine", response_model=list[BookingRequestResponse])
def list_my_requests(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    seeker_id = _require_seeker(current_user)
    rows = (
        _base_query(db)
        .filter(BookingRequest.seeker_id == seeker_id)
        .order_by(BookingRequest.created_at.desc())
        .all()
    )
    return [_to_response(r) for r in rows]


# ---------- GET /booking-requests/warden  (warden_requests.dart) ----------

@router.get("/warden", response_model=list[BookingRequestResponse])
def list_warden_requests(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warden_id = _require_warden(current_user)

    # All requests for hostels owned by this warden.
    rows = (
        _base_query(db)
        .join(Hostel, BookingRequest.hostel_id == Hostel.id)
        .filter(Hostel.warden_id == warden_id)
        .order_by(BookingRequest.created_at.desc())
        .all()
    )
    return [_to_response(r) for r in rows]


# ---------- PATCH /booking-requests/{id}/accept ----------

@router.patch("/{request_id}/accept", response_model=BookingRequestResponse)
def accept_request(
    request_id: str,
    payload: BookingRequestWardenAction,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warden_id = _require_warden(current_user)

    req = _base_query(db).filter(BookingRequest.id == request_id).first()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking request not found",
        )
    if req.hostel.warden_id != warden_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This request is not for one of your hostels",
        )

    if req.status == BookingStatus.accepted:
        # Idempotent — accepting an already-accepted request is a no-op.
        return _to_response(req)
    if req.status == BookingStatus.rejected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This request was already rejected",
        )

    req.status = BookingStatus.accepted
    req.warden_reply = payload.warden_reply
    req.responded_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
    return _to_response(req)


# ---------- PATCH /booking-requests/{id}/reject ----------

@router.patch("/{request_id}/reject", response_model=BookingRequestResponse)
def reject_request(
    request_id: str,
    payload: BookingRequestWardenAction,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    warden_id = _require_warden(current_user)

    req = _base_query(db).filter(BookingRequest.id == request_id).first()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking request not found",
        )
    if req.hostel.warden_id != warden_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This request is not for one of your hostels",
        )

    if req.status == BookingStatus.rejected:
        return _to_response(req)
    if req.status == BookingStatus.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This request was already accepted",
        )

    req.status = BookingStatus.rejected
    req.warden_reply = payload.warden_reply
    req.responded_at = datetime.utcnow()
    db.commit()
    db.refresh(req)
    return _to_response(req)