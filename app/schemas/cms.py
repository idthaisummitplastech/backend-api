from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class GenericCMSPayload(BaseModel):
    """Dynamic payload dictionary for CMS models."""
    data: Dict[str, Any]


class SiteSettingItem(BaseModel):
    key: str
    value: str


class SiteSettingsBatch(BaseModel):
    settings: Dict[str, Any]


class NavMenuItem(BaseModel):
    id: Optional[int] = None
    title: str
    url: str
    location: str
    section: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    is_maintenance: bool = False
    parent_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class ContactSubmissionCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    email: str = Field(..., min_length=5, max_length=255)
    subject: Optional[str] = None
    message: str = Field(..., min_length=5)


class ContactSubmissionResponse(ContactSubmissionCreate):
    id: int
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
