from typing import Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standardized enterprise API response wrapper."""
    success: bool = True
    message: Optional[str] = None
    data: Optional[T] = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic Paginated payload wrapper."""
    total: int
    page: int
    page_size: int
    items: List[T]


class StatusResponse(BaseModel):
    """Simple boolean status confirmation."""
    success: bool = True
    message: str = "Operasi berhasil dieksekusi."
