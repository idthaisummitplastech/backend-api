from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    name: str
    email: str
    department: Optional[str] = None
    requires_mfa: bool = False


class TokenPayload(BaseModel):
    sub: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    exp: Optional[int] = None


class LoginRequest(BaseModel):
    username_or_email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=4)
    totp_code: Optional[str] = Field(None, min_length=6, max_length=6)


class ApplicantLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=4)


class MFASetupResponse(BaseModel):
    secret: str
    qr_uri: str


class MFAVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class AdminBase(BaseModel):
    username: str
    name: str
    email: EmailStr
    role: str = "hr"
    department: Optional[str] = None
    is_mfa_enabled: bool = False


class AdminCreate(AdminBase):
    password: str = Field(..., min_length=6)


class AdminUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    department: Optional[str] = None
    password: Optional[str] = Field(None, min_length=6)


class AdminResponse(AdminBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    role: str
    mfa_enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
