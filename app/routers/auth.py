from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.utils.deps import get_current_user

from app.config import settings
from app.database import get_db
from app.models import User, PasswordResetOTP, UserRole
from app.schemas import (
    SignupRequest,
    LoginRequest,
    AuthResponse,
    RefreshRequest,
    AccessTokenResponse,
    ForgotPasswordRequest,
    VerifyOtpRequest,
    ResetPasswordRequest,
    GoogleAuthRequest,
    UpdateProfileRequest,
    UserSummary,
    ChangePasswordRequest,
    FcmTokenRequest,
)
from app.models import User, PasswordResetOTP, UserRole, RefreshToken
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    generate_refresh_token,
    refresh_token_expiry,
)
from app.utils.otp import generate_otp_code, send_otp_email
from app.utils.google_auth import verify_google_id_token, InvalidGoogleTokenError

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth_response(user: User, db: Session) -> AuthResponse:
    """Build a login/signup response with both an access token (short-
    lived JWT) and a refresh token (long-lived, stored in the DB)."""
    token = create_access_token(
        user_id=user.id, email=user.email, role=user.role.value
    )

    refresh = RefreshToken(
        user_id=user.id,
        token=generate_refresh_token(),
        expires_at=refresh_token_expiry(),
    )
    db.add(refresh)
    db.commit()

    return AuthResponse(
        access_token=token,
        refresh_token=refresh.token,
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        profile_picture_url=user.profile_picture_url,
    )


# ---------- signup.dart -> POST /auth/signup ----------

@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return _auth_response(user, db)


# ---------- login.dart -> POST /auth/login ----------

@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    # Same error for "no such user" and "wrong password" -- don't reveal
    # which one it was, so attackers can't use this to discover valid emails.
    invalid_credentials = HTTPException(status_code=401, detail="Invalid email or password")

    if not user or not user.hashed_password:
        raise invalid_credentials
    if not verify_password(payload.password, user.hashed_password):
        raise invalid_credentials

        return _auth_response(user, db)


# ---------- forgot_password.dart -> POST /auth/forgot-password ----------

@router.post("/forgot-password", status_code=status.HTTP_200_OK)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    # Always return the same response whether or not the email exists,
    # so this endpoint can't be used to check which emails are registered.
    if user:
        code = generate_otp_code()
        otp = PasswordResetOTP(
            user_id=user.id,
            code=code,
            expires_at=datetime.utcnow()
            + timedelta(minutes=settings.otp_expire_minutes),
        )
        db.add(otp)
        db.commit()
        send_otp_email(user.email, code)

    return {"message": "If that email is registered, a reset code has been sent."}


# ---------- otp.dart -> POST /auth/verify-otp ----------

@router.post("/verify-otp", status_code=status.HTTP_200_OK)
def verify_otp(payload: VerifyOtpRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid code")

    otp = (
        db.query(PasswordResetOTP)
        .filter(
            PasswordResetOTP.user_id == user.id,
            PasswordResetOTP.code == payload.code,
            PasswordResetOTP.is_used == False,  # noqa: E712
        )
        .order_by(PasswordResetOTP.created_at.desc())
        .first()
    )

    if not otp or otp.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    return {"message": "Code verified"}


# ---------- called after otp.dart verifies -> POST /auth/reset-password ----------

@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid code")

    otp = (
        db.query(PasswordResetOTP)
        .filter(
            PasswordResetOTP.user_id == user.id,
            PasswordResetOTP.code == payload.code,
            PasswordResetOTP.is_used == False,  # noqa: E712
        )
        .order_by(PasswordResetOTP.created_at.desc())
        .first()
    )

    if not otp or otp.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    user.hashed_password = hash_password(payload.new_password)
    otp.is_used = True
    db.commit()

    return {"message": "Password reset successfully"}


# ---------- new Google button -> POST /auth/google ----------

@router.post("/google", response_model=AuthResponse)
def google_auth(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    try:
        google_payload = verify_google_id_token(payload.id_token)
    except InvalidGoogleTokenError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    google_id = google_payload["sub"]
    email = google_payload["email"]
    name = google_payload.get("name", email.split("@")[0])

    user = db.query(User).filter(User.google_id == google_id).first()

    if not user:
        # If an account with this email already exists (e.g. signed up with
        # a password before), link Google to it instead of creating a duplicate.
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.google_id = google_id
        else:
            user = User(
                full_name=name,
                email=email,
                google_id=google_id,
                role=payload.role,
            )
            db.add(user)
        db.commit()
        db.refresh(user)

        return _auth_response(user, db)

# ---------- Profile / Account ----------

@router.patch("/me", response_model=UserSummary)
def update_profile(
    payload: UpdateProfileRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Update the logged-in user's name and/or phone. Email change is
    intentionally not supported here — that requires its own
    verification flow."""
    user_id = current_user["sub"]
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.phone is not None:
        cleaned = payload.phone.strip()
        user.phone = cleaned if cleaned else None
    if payload.profile_picture_url is not None:
        # Empty string means "remove the picture".
        cleaned = payload.profile_picture_url.strip()
        user.profile_picture_url = cleaned if cleaned else None

    db.commit()
    db.refresh(user)
    return user


@router.patch("/change-password", status_code=status.HTTP_200_OK)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Change the logged-in user's password. Requires the current
    password for verification."""
    user_id = current_user["sub"]
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Google-only accounts have no password of ours.
    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account has no password set (signed up via Google)",
        )

    if not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if payload.old_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the current one",
        )

    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"status": "ok"}

@router.patch("/me/fcm-token", status_code=status.HTTP_200_OK)
def update_fcm_token(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Save the device's FCM token so the backend can send push
    notifications to this user."""
    token = payload.get("fcm_token")
    if not token or not isinstance(token, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fcm_token is required",
        )
    user_id = current_user["sub"]
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.fcm_token = token
    db.commit()
    return {"status": "ok"}

# ---------- FCM token ----------

@router.patch("/me/fcm-token", status_code=status.HTTP_200_OK)
def update_fcm_token(
    payload: FcmTokenRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Save the device's FCM token so the backend can send push
    notifications to this user."""
    user_id = current_user["sub"]
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.fcm_token = payload.fcm_token
    db.commit()
    return {"status": "ok"}

# ---------- Refresh tokens ----------

@router.post("/refresh", response_model=AccessTokenResponse)
def refresh_access_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a fresh access token.

    Refresh-token rotation: the incoming refresh token is revoked and a
    new one is issued alongside the new access token.
    """
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token == payload.refresh_token)
        .first()
    )
    if row is None or row.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked refresh token",
        )
    if row.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
        )

    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )

    # Rotate: revoke the old refresh token, issue a new one.
    row.revoked_at = datetime.utcnow()

    new_refresh = RefreshToken(
        user_id=user.id,
        token=generate_refresh_token(),
        expires_at=refresh_token_expiry(),
    )
    db.add(new_refresh)
    db.commit()

    new_access = create_access_token(
        user_id=user.id, email=user.email, role=user.role.value
    )

    return AccessTokenResponse(
        access_token=new_access,
        refresh_token=new_refresh.token,
    )

@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Revoke the given refresh token. Idempotent — logging out with an
    already-revoked token still returns 200.

    Note: the access token can't be revoked (it's stateless) — it will
    still work until it expires. But because it's short-lived, that's a
    small window. The refresh token, however, is dead on arrival.
    """
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token == payload.refresh_token)
        .first()
    )
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.commit()

    return {"status": "ok"}