from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc
from app.db.base_class import Base

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    Enterprise Generic CRUD Repository implementing OOP design pattern.
    Provides standard reusable data-access operations without code duplication.
    """

    def __init__(self, model: Type[ModelType]):
        self.model = model

    def get(self, db: Session, id: Any) -> Optional[ModelType]:
        """Fetch single record by its primary key ID."""
        return db.query(self.model).filter(self.model.id == id).first()

    def get_by_attribute(self, db: Session, attr: str, value: Any) -> Optional[ModelType]:
        """Fetch single record by any unique attribute dynamically."""
        column = getattr(self.model, attr, None)
        if column is None:
            return None
        return db.query(self.model).filter(column == value).first()

    def get_multi(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        order_by: Any = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[ModelType]:
        """Fetch multiple records with pagination, dynamic filters, and custom ordering."""
        query = db.query(self.model)

        if filters:
            for key, val in filters.items():
                if hasattr(self.model, key) and val is not None:
                    query = query.filter(getattr(self.model, key) == val)

        if order_by is not None:
            query = query.order_by(order_by)
        elif hasattr(self.model, "id"):
            query = query.order_by(self.model.id.desc())

        return query.offset(skip).limit(limit).all()

    def count(self, db: Session, filters: Optional[Dict[str, Any]] = None) -> int:
        """Count total matching records."""
        query = db.query(self.model)
        if filters:
            for key, val in filters.items():
                if hasattr(self.model, key) and val is not None:
                    query = query.filter(getattr(self.model, key) == val)
        return query.count()

    def create(self, db: Session, *, obj_in: Union[CreateSchemaType, Dict[str, Any]]) -> ModelType:
        """Insert a new record from Pydantic schema or dictionary."""
        if isinstance(obj_in, dict):
            obj_in_data = obj_in
        else:
            obj_in_data = obj_in.model_dump(exclude_unset=True)

        db_obj = self.model(**obj_in_data)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def update(
        self,
        db: Session,
        *,
        db_obj: ModelType,
        obj_in: Union[UpdateSchemaType, Dict[str, Any]],
    ) -> ModelType:
        """Update an existing database object cleanly."""
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)

        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def remove(self, db: Session, *, id: Any) -> Optional[ModelType]:
        """Delete a record by ID."""
        obj = db.query(self.model).get(id)
        if obj:
            db.delete(obj)
            db.commit()
        return obj
