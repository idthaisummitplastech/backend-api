from typing import Any, Optional
from sqlalchemy.orm import Session
from app.crud.base import CRUDBase
from app.models.auth import RecruitmentAdmin, User
from app.schemas.auth import AdminCreate, AdminUpdate
from app.core.security import get_password_hash, verify_password


class CRUDAdmin(CRUDBase[RecruitmentAdmin, AdminCreate, AdminUpdate]):
    """Specialized repository for Recruitment Admin & HR users."""

    def get_by_email(self, db: Session, email: str) -> Optional[RecruitmentAdmin]:
        return self.get_by_attribute(db, "email", email.strip().lower())

    def get_by_username(self, db: Session, username: str) -> Optional[RecruitmentAdmin]:
        return self.get_by_attribute(db, "username", username.strip().lower())

    def create(self, db: Session, *, obj_in: AdminCreate) -> RecruitmentAdmin:
        data = obj_in.model_dump()
        data["password"] = get_password_hash(data["password"])
        data["email"] = data["email"].strip().lower()
        data["username"] = data["username"].strip().lower()
        return super().create(db, obj_in=data)

    def authenticate(self, db: Session, *, username_or_email: str, password: str) -> Optional[RecruitmentAdmin]:
        val = username_or_email.strip().lower()
        admin = self.get_by_username(db, val) or self.get_by_email(db, val)
        if not admin or not verify_password(password, admin.password):
            return None
        return admin


class CRUDUser(CRUDBase[User, Any, Any]):
    """Specialized repository for Company Profile CMS users."""

    def get_by_email(self, db: Session, email: str) -> Optional[User]:
        return self.get_by_attribute(db, "email", email.strip().lower())

    def authenticate(self, db: Session, *, email: str, password: str) -> Optional[User]:
        user = self.get_by_email(db, email)
        if not user or not verify_password(password, user.password):
            return None
        return user


crud_admin = CRUDAdmin(RecruitmentAdmin)
crud_user = CRUDUser(User)
