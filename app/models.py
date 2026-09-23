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
    Text,
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

class BookingStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"

class NotificationType(str, enum.Enum):
    booking_created = "booking_created"
    booking_accepted = "booking_accepted"
    booking_rejected = "booking_rejected"
    booking_cancelled = "booking_cancelled"

# ── Auth ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    fcm_token = Column(String, nullable=True)

    # Nullable because a user who signs up via Google has no password of ours.
    hashed_password = Column(String, nullable=True)

    # Optional contact number — added post-signup from the Profile screen.
    phone = Column(String, nullable=True)

    # Optional Cloudinary URL for the user's avatar. Null means no photo
    # yet — the Flutter side falls back to initials.
    profile_picture_url = Column(String, nullable=True)

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

class BookingRequest(Base):
    """A seeker asking a warden to book a specific room, for a specific
    move-in date. Wardens accept or reject; the request is immutable
    after that."""

    __tablename__ = "booking_requests"

    id = Column(String, primary_key=True, default=_uuid)
    seeker_id = Column(
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
    room_id = Column(
        String,
        ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    move_in_date = Column(DateTime, nullable=False)
    message = Column(Text, nullable=True)
    warden_reply = Column(Text, nullable=True)

    status = Column(
        Enum(BookingStatus),
        nullable=False,
        default=BookingStatus.pending,
        index=True,
    )

    seat_requested = Column(Boolean, nullable=False, default=False, server_default="false")
    seat_count = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime, default=lambda: datetime.utcnow())
    responded_at = Column(DateTime, nullable=True)

    seeker = relationship("User", foreign_keys=[seeker_id])
    hostel = relationship("Hostel")
    room = relationship("Room")

class Notification(Base):
    """In-app notification for a user. Created by booking events; the
    Flutter drawer and alerts tab render these. `related_id` points at
    the object the notification is about (currently a BookingRequest id),
    so tapping a notification can navigate to the right screen."""

    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = Column(Enum(NotificationType), nullable=False)

    title = Column(String, nullable=False)
    body = Column(String, nullable=True)

    # Optional FK to the related object. Kept as a plain string (not a
    # real FK) so we don't have to worry about cascade behavior when the
    # target row is deleted — the notification just becomes stale.
    related_id = Column(String, nullable=True, index=True)

    is_read = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    user = relationship("User")

class RefreshToken(Base):
    """A long-lived token that lets the client obtain new access tokens
    without re-authenticating. Stored server-side so it can be revoked.

    One row per active session. A user with the app on two devices will
    have two rows. Logout revokes one (or all) rows.
    """

    __tablename__ = "refresh_tokens"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # A random URL-safe string, not a JWT — it's looked up in the DB on
    # every refresh, so it doesn't need to be self-describing.
    token = Column(String, unique=True, index=True, nullable=False)

    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.utcnow())

    # Set when the token is used to refresh, logged out, or otherwise
    # invalidated. A revoked token can't be reused.
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User")