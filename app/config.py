"""
All configurable values live here, pulled from environment variables.
Nothing secret is ever hardcoded in the code itself -- it all comes from
a local .env file (which should NEVER be committed to git).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database ---
    # Example: postgresql://user:password@localhost:5432/hostel_yaar
    database_url: str = "sqlite:///./hostel_yaar_dev.db"

    # --- JWT (used to sign OUR OWN tokens, issued after login/signup) ---
    jwt_secret_key: str = "CHANGE_ME_DEV_ONLY_NOT_FOR_PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24  # 1 day

    # How long a refresh token is valid. After this, the user must log
    # in again with their password.
    refresh_token_expire_days: int = 30

    # --- Google OAuth (used to verify tokens the Flutter app sends us) ---
    # This is the "Web client ID" from Google Cloud Console, NOT a secret.
    google_client_id: str = ""

    # --- Firebase Admin SDK (for sending push notifications) ---
    # Path to the service account JSON file. In production this points
    # at a file mounted from an environment variable.
    firebase_credentials_path: str = "firebase-service-account.json"

    # --- OTP (for forgot-password flow) ---
    otp_expire_minutes: int = 10

    # --- Email sending (for OTP codes) ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
