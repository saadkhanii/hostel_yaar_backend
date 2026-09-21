from app.models import BookingType, User  # add to existing app.models import
from app.utils.fcm import send_push
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
from app.utils.notifications import (
    notify_seeker_booking_accepted,
    notify_seeker_booking_rejected,
    notify_warden_booking_cancelled,
    notify_warden_booking_created,
)

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
        seat_requested=req.seat_requested,
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

def _consume_seat(db: Session, room: Room, seat_requested: bool) -> None:
    """Mark a room's availability as reduced by an accepted booking.

    - Per-Seat request: decrement available_seats by 1. If it drops to 0,
      the room shows as full.
    - Whole-room request: set vacant = False and available_seats = 0.
    """
    if seat_requested:
        room.available_seats = max(0, (room.available_seats or 0) - 1)
        if room.available_seats == 0:
            room.vacant = False
    else:
        room.vacant = False
        room.available_seats = 0


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
        seat_requested=room.booking_type == BookingType.seat,
        move_in_date=payload.move_in_date,
        message=payload.message,
        status=BookingStatus.pending,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    # Reload with eager relations for the response.
    req = _base_query(db).filter(BookingRequest.id == req.id).first()

    notify_warden_booking_created(
        db,
        warden_id=req.hostel.warden_id,
        seeker_name=req.seeker.full_name if req.seeker else "A seeker",
        hostel_name=req.hostel.name if req.hostel else "",
        room_number=req.room.number if req.room else "",
        booking_id=req.id,
    )
    db.commit()

    # Send a push to the warden's device, if any.
    warden = db.query(User).filter(User.id == req.hostel.warden_id).first()
    if warden and warden.fcm_token:
        send_push(
            token=warden.fcm_token,
            title="New booking request",
            body=f"{req.seeker.full_name if req.seeker else 'A seeker'} requested Room {req.room.number if req.room else ''}.",
            data={"type": "booking_created", "booking_id": req.id},
        )

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

    # Consume the room/seat so it no longer shows as available.
    if req.room:
        _consume_seat(db, req.room, req.seat_requested)

    db.commit()
    db.refresh(req)

    # Notify the seeker.
    notify_seeker_booking_accepted(
        db,
        seeker_id=req.seeker_id,
        hostel_name=req.hostel.name if req.hostel else "",
        room_number=req.room.number if req.room else "",
        booking_id=req.id,
    )
    db.commit()

    seeker = db.query(User).filter(User.id == req.seeker_id).first()
    if seeker and seeker.fcm_token:
        send_push(
            token=seeker.fcm_token,
            title="Request accepted",
            body=f"Your request for Room {req.room.number if req.room else ''} was accepted.",
            data={"type": "booking_accepted", "booking_id": req.id},
        )

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

    # Notify the seeker.
    notify_seeker_booking_rejected(
        db,
        seeker_id=req.seeker_id,
        hostel_name=req.hostel.name if req.hostel else "",
        room_number=req.room.number if req.room else "",
        booking_id=req.id,
    )
    db.commit()

    seeker = db.query(User).filter(User.id == req.seeker_id).first()
    if seeker and seeker.fcm_token:
        send_push(
            token=seeker.fcm_token,
            title="Request rejected",
            body=f"Your request for Room {req.room.number if req.room else ''} was rejected.",
            data={"type": "booking_rejected", "booking_id": req.id},
        )

    return _to_response(req)

# ---------- DELETE /booking-requests/{id}  (seeker cancels own pending request) ----------

@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_booking_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Seeker cancels their own pending request. Rejected/accepted
    requests cannot be cancelled — the warden already acted."""
    seeker_id = _require_seeker(current_user)

    req = _base_query(db).filter(BookingRequest.id == request_id).first()
    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking request not found",
        )
    if req.seeker_id != seeker_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This is not your request",
        )
    if req.status != BookingStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a {req.status.value} request",
        )

    # Snapshot values we need before deleting.
    warden_id = req.hostel.warden_id if req.hostel else None
    seeker_name = req.seeker.full_name if req.seeker else "A seeker"
    hostel_name = req.hostel.name if req.hostel else ""
    room_number = req.room.number if req.room else ""

    db.delete(req)
    db.commit()

    # Notify the warden.
    if warden_id:
        notify_warden_booking_cancelled(
            db,
            warden_id=warden_id,
            seeker_name=seeker_name,
            hostel_name=hostel_name,
            room_number=room_number,
            booking_id=request_id,
        )
        db.commit()

    return None