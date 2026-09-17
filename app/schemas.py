from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.models import BookingStatus, BookingType, HostelType, UserRole


# ---------- Auth: signup / login ----------

class SignupRequest(BaseModel):
    full_name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=6)
    role: UserRole = UserRole.seeker


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    full_name: str
    email: str
    role: UserRole


# ---------- Forgot password / OTP ----------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=6)


# ---------- Google OAuth ----------

class GoogleAuthRequest(BaseModel):
    # This is the ID token the Flutter app receives from google_sign_in
    # after the user picks their Google account.
    id_token: str
    # Only used if this is a first-time signup via Google (role picked in-app).
    role: UserRole = UserRole.seeker


# ---------- Rooms ----------

class RoomCreate(BaseModel):
    """Payload for creating a room. Sent inside HostelCreate, and also
    used as the request body for the standalone add-room endpoint."""

    number: str = Field(min_length=1)
    booking_type: BookingType
    room_type: int = Field(ge=1, le=6)
    available_seats: int = Field(default=0, ge=0)
    attached_washroom: bool = False
    price: int = Field(default=0, ge=0)
    advance: int = Field(default=0, ge=0)
    vacant: bool = True
    availability_dates: list[str] = Field(default_factory=list)


class RoomUpdate(BaseModel):
    """All fields optional — send only what changed."""

    number: Optional[str] = Field(default=None, min_length=1)
    booking_type: Optional[BookingType] = None
    room_type: Optional[int] = Field(default=None, ge=1, le=6)
    available_seats: Optional[int] = Field(default=None, ge=0)
    attached_washroom: Optional[bool] = None
    price: Optional[int] = Field(default=None, ge=0)
    advance: Optional[int] = Field(default=None, ge=0)
    vacant: Optional[bool] = None
    availability_dates: Optional[list[str]] = None


class RoomResponse(BaseModel):
    id: str
    hostel_id: str
    number: str
    booking_type: BookingType
    room_type: int
    available_seats: int
    attached_washroom: bool
    price: int
    advance: int
    vacant: bool
    availability_dates: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------- Hostels ----------

class HostelCreate(BaseModel):
    """Payload for POST /hostels. Rooms are created alongside the hostel
    in the same request, since the warden builds them together in the
    Add Hostel flow."""

    name: str = Field(min_length=1)
    city: str = Field(min_length=1)
    address: str = Field(min_length=1)
    type: HostelType
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    facilities: list[str] = Field(default_factory=list)
    photos: list[str] = Field(default_factory=list)
    phone: str = Field(min_length=1)
    whatsapp: Optional[str] = None
    in_app_chat: bool = True
    active: bool = True
    rooms: list[RoomCreate] = Field(default_factory=list)


class HostelUpdate(BaseModel):
    """All fields optional — send only what changed."""

    name: Optional[str] = Field(default=None, min_length=1)
    city: Optional[str] = Field(default=None, min_length=1)
    address: Optional[str] = Field(default=None, min_length=1)
    type: Optional[HostelType] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    facilities: Optional[list[str]] = None
    photos: Optional[list[str]] = None
    phone: Optional[str] = Field(default=None, min_length=1)
    whatsapp: Optional[str] = None
    in_app_chat: Optional[bool] = None
    active: Optional[bool] = None


class HostelSummary(BaseModel):
    id: str
    warden_id: str
    name: str
    city: str
    address: str
    type: HostelType
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    facilities: list[str]
    photos: list[str]
    phone: str
    whatsapp: Optional[str] = None
    in_app_chat: bool
    active: bool
    starting_price: int = 0
    has_vacancy: bool = False
    room_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HostelDetail(HostelSummary):
    """Full hostel with its rooms. Used by GET /hostels/{id} and the
    warden's own listing view."""

    rooms: list[RoomResponse] = Field(default_factory=list)

# ---------- Booking Requests ----------

class BookingRequestCreate(BaseModel):
    """Payload for POST /booking-requests. The seeker is derived from
    the JWT — they can't create requests on behalf of anyone else."""

    hostel_id: str
    room_id: str
    move_in_date: datetime
    message: Optional[str] = Field(default=None, max_length=500)


class BookingRequestWardenAction(BaseModel):
    """Body for accept/reject. Both fields are optional."""

    warden_reply: Optional[str] = Field(default=None, max_length=500)


class BookingRequestResponse(BaseModel):
    """Full request shape, including a compact snapshot of the hostel
    and room so both seeker and warden screens can render without
    extra fetches."""

    id: str
    seeker_id: str
    hostel_id: str
    room_id: str
    move_in_date: datetime
    message: Optional[str] = None
    warden_reply: Optional[str] = None
    status: BookingStatus # 'pending' | 'accepted' | 'rejected'
    created_at: datetime
    responded_at: Optional[datetime] = None

    # Denormalized snapshots for list views.
    seeker_name: str = ""
    seeker_phone: Optional[str] = None
    hostel_name: str = ""
    hostel_city: str = ""
    room_number: str = ""
    room_type: int = 0
    room_booking_type: str = ""
    room_price: int = 0
    room_advance: int = 0