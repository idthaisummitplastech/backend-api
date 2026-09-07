import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union
import bcrypt
from jose import JWTError, jwt
import pyotp

from app.core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Securely verify password against bcrypt hash using constant-time comparison."""
    if not plain_password or not hashed_password:
        return False
    try:
        # Handle string encoding for bcrypt
        pwd_bytes = plain_password.encode("utf-8")
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Generate secure bcrypt password hash with salt factor 12."""
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def create_access_token(
    subject: Union[str, Any],
    role: str = "applicant",
    department: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate cryptographically signed JWT access token with expiration and roles."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "sub": str(subject),
        "role": role,
        "department": department,
        "iat": now,
        "exp": expire,
        "iss": "itsp-auth-service",
    }
    if extra_claims:
        to_encode.update(extra_claims)

    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT access token signature and expiration."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            issuer="itsp-auth-service",
        )
        return payload
    except JWTError:
        return None


# --- 2FA / MFA (TOTP) Security ---
def generate_totp_secret() -> str:
    """Generate a high-entropy base32 secret for Google Authenticator / Microsoft Authenticator."""
    return pyotp.random_base32()


def generate_totp_uri(secret: str, username: str, issuer: str = "PT ITSP Recruitment") -> str:
    """Generate standard otpauth URI compatible with authenticator apps."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    """Verify time-based one-time password with a 1-step drift window (30 seconds allowance)."""
    if not secret or not code:
        return False
    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(code.strip(), valid_window=valid_window)
    except Exception:
        return False
