"""Pydantic schemas for Department and Section."""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


# ---- Section Schemas ----
class SectionBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True
    sort_order: int = 0


class SectionCreate(SectionBase):
    department_id: int


class SectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    department_id: Optional[int] = None


class SectionResponse(SectionBase):
    id: int
    department_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---- Department Schemas ----
class DepartmentBase(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True
    sort_order: int = 0


class DepartmentCreate(DepartmentBase):
    pass


class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class DepartmentResponse(DepartmentBase):
    id: int
    sections: List[SectionResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DepartmentSimple(BaseModel):
    """Lightweight response for dropdowns (no sections)."""
    id: int
    name: str
    code: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)
