import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Enums ────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    seeker = "seeker"
    warden = "warden"


class HostelType(str, enum.Enum):
    boys = "Boys"
    girls = "Girls"
    mixed = "Mixed"


class BookingType(str, enum.Enum):
    room = "Room"   # whole room booked together
    seat = "Seat"   # individual seat/bed booked separately


# ── Auth ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)

    # Nullable because a user who signs up via Google has no password of ours.
    hashed_password = Column(String, nullable=True)

    role = Column(Enum(UserRole), nullable=False, default=UserRole.seeker)

    # Set when the account was created/linked via "Continue with Google".
    google_id = Column(String, unique=True, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    otps = relationship(
        "PasswordResetOTP",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    hostels = relationship(
        "Hostel",
        back_populates="warden",
        cascade="all, delete-orphan",
    )


class PasswordResetOTP(Base):
    """A 6-digit code issued for the forgot-password flow (otp.dart)."""

    __tablename__ = "password_reset_otps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)

    code = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)

    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    user = relationship("User", back_populates="otps")


# ── Hostels ──────────────────────────────────────────────────────────

class Hostel(Base):
    """A hostel listed by a warden. A warden can own many hostels."""

    __tablename__ = "hostels"

    id = Column(String, primary_key=True, default=_uuid)
    warden_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String, nullable=False)
    city = Column(String, nullable=False)
    address = Column(String, nullable=False)
    type = Column(Enum(HostelType), nullable=False)

    # Nullable for now; will be populated when the map view is built.
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # JSONB on Postgres: stores lists (and dicts) efficiently, and lets
    # you query inside them later (e.g. WHERE facilities @> '["WiFi"]').
    facilities = Column(JSONB, nullable=False, default=list)
    photos = Column(JSONB, nullable=False, default=list)

    phone = Column(String, nullable=False)
    whatsapp = Column(String, nullable=True)
    in_app_chat = Column(Boolean, nullable=False, default=True)

    # Wardens can hide a listing without deleting it.
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(
        DateTime,
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
    )

    warden = relationship("User", back_populates="hostels")
    rooms = relationship(
        "Room",
        back_populates="hostel",
        cascade="all, delete-orphan",
    )


class Room(Base):
    """A room within a hostel. Can be listed as a whole room or per seat."""

    __tablename__ = "rooms"

    id = Column(String, primary_key=True, default=_uuid)
    hostel_id = Column(
        String,
        ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    number = Column(String, nullable=False)      # "101", "Ground Floor A"
    booking_type = Column(Enum(BookingType), nullable=False)
    room_type = Column(Integer, nullable=False)   # 1–6 seater
    available_seats = Column(Integer, nullable=False, default=0)
    attached_washroom = Column(Boolean, nullable=False, default=False)

    # Monthly rent + advance security, both in PKR.
    price = Column(Integer, nullable=False, default=0)
    advance = Column(Integer, nullable=False, default=0)

    # Only meaningful for whole-room listings; kept in sync with
    # booking_type == Room. For Seat listings, availability comes from
    # available_seats instead.
    vacant = Column(Boolean, nullable=False, default=True)

    # List of ISO-8601 date strings, e.g. ["2026-09-20", "2026-10-01"].
    # One entry per available seat for a Per Seat room, or a single entry
    # for a vacant Complete Room.
    availability_dates = Column(JSONB, nullable=False, default=list)

    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    updated_at = Column(
        DateTime,
        default=lambda: datetime.utcnow(),
        onupdate=lambda: datetime.utcnow(),
    )

    hostel = relationship("Hostel", back_populates="rooms")

class SavedHostel(Base):
    """A seeker has saved a hostel for later. Unique per (user, hostel) pair."""

    __tablename__ = "saved_hostels"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hostel_id = Column(
        String,
        ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    __table_args__ = (
        UniqueConstraint("user_id", "hostel_id", name="uq_saved_hostel_user_hostel"),
    )

    user = relationship("User", backref="saved_hostels")
    hostel = relationship("Hostel", backref="saved_by")