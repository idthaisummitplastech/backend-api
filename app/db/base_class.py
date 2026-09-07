from datetime import datetime, timezone
import re
from typing import Any
from sqlalchemy import DateTime, Column
from sqlalchemy.orm import DeclarativeBase, declared_attr


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    id: Any
    __name__: str

    # Automatically generate __tablename__ in snake_case if not explicitly defined
    @declared_attr.directive
    def __tablename__(cls) -> str:
        # Converts CamelCase to snake_case plural
        s = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", cls.__name__)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s).lower() + "s"


class TimestampMixin:
    """Reusable OOP Mixin to inject created_at and updated_at automatically."""
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=True,
    )
