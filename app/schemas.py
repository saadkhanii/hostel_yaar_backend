from pydantic import BaseModel, EmailStr, Field

from app.models import UserRole


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
