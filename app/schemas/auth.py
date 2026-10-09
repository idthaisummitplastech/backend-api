from datetime import datetime, timezone
from typing import Optional
from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field


def get_default_password() -> str:
    """Dynamic default password Itsp@YYYY — YYYY = current year, hash only on create/reset."""
    return f"Itsp@{datetime.now(timezone.utc).year}"


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    name: str
    full_name: Optional[str] = None
    fullName: Optional[str] = None
    email: str
    department: Optional[str] = None
    requires_mfa: bool = False
    id: Optional[int] = None
    applicant_id: Optional[int] = None
    is_first_login: Optional[bool] = None
    employee_id: Optional[str] = None


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    exp: Optional[int] = None


class LoginRequest(BaseModel):
    # Employee ID primary (004.02.16) — dual-mode fallback to username/email for 6 months
    username_or_email: str = Field(
        ..., min_length=3, max_length=255,
        validation_alias=AliasChoices("username_or_email", "employee_id", "employee_id_or_email", "login", "email"),
        description="Employee ID (004.02.16) primary, email/username fallback",
    )
    # Alias helper for frontend baru
    employee_id_or_email: Optional[str] = Field(None, validation_alias=AliasChoices("employee_id_or_email", "employeeId"))
    password: str = Field(..., min_length=4)
    totp_code: Optional[str] = Field(None, min_length=6, max_length=6)

    @property
    def login_identifier(self) -> str:
        return (self.employee_id_or_email or self.username_or_email or "").strip()


class ApplicantLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=4)


class MFASetupResponse(BaseModel):
    secret: str
    qr_uri: str


class MFAVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class AdminBase(BaseModel):
    employee_id: Optional[str] = Field(None, max_length=50, description="Employee ID immutable 004.02.16")
    username: str
    name: str
    email: EmailStr
    role: str = "hr"
    department: Optional[str] = None
    is_mfa_enabled: bool = False
    is_active: bool = True
    portal_access: str = "both"  # perusahaan | karir | both
    is_first_login: bool = True


class AdminCreate(AdminBase):
    # password optional — jika kosong pakai Itsp@YYYY
    password: Optional[str] = Field(None, min_length=6)


class AdminUpdate(BaseModel):
    employee_id: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    department: Optional[str] = None
    password: Optional[str] = Field(None, min_length=6)
    is_active: Optional[bool] = None
    portal_access: Optional[str] = None
    is_first_login: Optional[bool] = None


class AdminResponse(AdminBase):
    id: int
    created_at: datetime
    employee_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    mfa_enabled: bool
    is_active: bool = True
    portal_access: str = "both"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
