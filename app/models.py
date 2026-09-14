import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Boolean, Enum, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    seeker = "seeker"
    warden = "warden"


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

    otps = relationship("PasswordResetOTP", back_populates="user", cascade="all, delete-orphan")


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
