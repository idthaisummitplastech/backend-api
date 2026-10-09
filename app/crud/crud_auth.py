from typing import Any, Optional
from sqlalchemy.orm import Session
from app.crud.base import CRUDBase
from app.models.auth import RecruitmentAdmin, User
from app.schemas.auth import AdminCreate, AdminUpdate, get_default_password
from app.core.security import get_password_hash, verify_password


class CRUDAdmin(CRUDBase[RecruitmentAdmin, AdminCreate, AdminUpdate]):
    """Specialized repository for Recruitment Admin & HR users — Employee ID primary."""

    def get_by_email(self, db: Session, email: str) -> Optional[RecruitmentAdmin]:
        return self.get_by_attribute(db, "email", email.strip().lower())

    def get_by_username(self, db: Session, username: str) -> Optional[RecruitmentAdmin]:
        return self.get_by_attribute(db, "username", username.strip().lower())

    def get_by_employee_id(self, db: Session, employee_id: str) -> Optional[RecruitmentAdmin]:
        eid = employee_id.strip()
        if not eid:
            return None
        return self.get_by_attribute(db, "employee_id", eid)

    def create(self, db: Session, *, obj_in: AdminCreate) -> RecruitmentAdmin:
        data = obj_in.model_dump()
        # Dynamic default password Itsp@YYYY if empty
        raw_pwd = data.get("password")
        if not raw_pwd:
            raw_pwd = get_default_password()
            data["is_first_login"] = True
        else:
            # If caller explicitly provides password, keep is_first_login as payload (default True) but allow False
            pass
        data["password"] = get_password_hash(raw_pwd)
        data["email"] = data["email"].strip().lower()
        data["username"] = data["username"].strip().lower()
        if data.get("employee_id"):
            data["employee_id"] = str(data["employee_id"]).strip()
            if not data["employee_id"]:
                data["employee_id"] = None
        return super().create(db, obj_in=data)

    def update(self, db: Session, *, db_obj: RecruitmentAdmin, obj_in: Any) -> RecruitmentAdmin:
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)
        if "password" in update_data and update_data["password"]:
            update_data["password"] = get_password_hash(update_data["password"])
            # Reset is_first_login if password was reset to default explicitly handled elsewhere
        elif "password" in update_data and not update_data["password"]:
            update_data.pop("password", None)
        if "email" in update_data and update_data["email"]:
            update_data["email"] = update_data["email"].strip().lower()
        if "username" in update_data and update_data["username"]:
            update_data["username"] = update_data["username"].strip().lower()
        if "employee_id" in update_data and update_data["employee_id"] is not None:
            eid = str(update_data["employee_id"]).strip()
            update_data["employee_id"] = eid if eid else None
        return super().update(db, db_obj=db_obj, obj_in=update_data)

    def reset_to_default_password(self, db: Session, *, db_obj: RecruitmentAdmin) -> RecruitmentAdmin:
        """Reset password to Itsp@YYYY and force is_first_login."""
        new_pwd = get_default_password()
        db_obj.password = get_password_hash(new_pwd)
        db_obj.is_first_login = True
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def authenticate(self, db: Session, *, username_or_email: str, password: str) -> Optional[RecruitmentAdmin]:
        """Dual-mode: employee_id (exact) -> username (lower) -> email (lower) for 6 months fallback."""
        raw = (username_or_email or "").strip()
        if not raw:
            return None
        val_lower = raw.lower()
        # 1) Try Employee ID exact (e.g. 004.02.16)
        admin = self.get_by_employee_id(db, raw)
        if admin and verify_password(password, admin.password):
            return admin
        # 2) Username fallback
        admin = self.get_by_username(db, val_lower)
        if admin and verify_password(password, admin.password):
            return admin
        # 3) Email fallback
        admin = self.get_by_email(db, val_lower)
        if admin and verify_password(password, admin.password):
            return admin
        return None


class CRUDUser(CRUDBase[User, Any, Any]):
    """Specialized repository for Company Profile CMS users — Employee ID primary."""

    def get_by_email(self, db: Session, email: str) -> Optional[User]:
        return self.get_by_attribute(db, "email", email.strip().lower())

    def get_by_employee_id(self, db: Session, employee_id: str) -> Optional[User]:
        eid = (employee_id or "").strip()
        if not eid:
            return None
        return self.get_by_attribute(db, "employee_id", eid)

    def authenticate(self, db: Session, *, email: str, password: str) -> Optional[User]:
        """Dual-mode: employee_id exact -> email lower fallback."""
        raw = (email or "").strip()
        if not raw:
            return None
        user = self.get_by_employee_id(db, raw)
        if user and verify_password(password, user.password):
            return user
        user = self.get_by_email(db, raw.lower())
        if user and verify_password(password, user.password):
            return user
        return user if user and verify_password(password, user.password) else None

    def authenticate_dual(self, db: Session, *, identifier: str, password: str) -> Optional[User]:
        raw = (identifier or "").strip()
        if not raw:
            return None
        user = self.get_by_employee_id(db, raw)
        if user and verify_password(password, user.password):
            return user
        user = self.get_by_email(db, raw.lower())
        if user and verify_password(password, user.password):
            return user
        # also try username if exists
        col = getattr(self.model, "username", None)
        if col is not None:
            u = db.query(self.model).filter(col == raw.lower()).first()
            if u and verify_password(password, u.password):
                return u
        return None

    def create_with_default_pwd(self, db: Session, *, obj_in: Any) -> User:
        from app.schemas.auth import get_default_password
        data = obj_in if isinstance(obj_in, dict) else obj_in.model_dump()
        if not data.get("password"):
            data["password"] = get_password_hash(get_default_password())
            data["is_first_login"] = True
        else:
            data["password"] = get_password_hash(data["password"])
        if data.get("email"):
            data["email"] = data["email"].strip().lower()
        if data.get("username"):
            data["username"] = data["username"].strip().lower()
        if data.get("employee_id"):
            eid = str(data["employee_id"]).strip()
            data["employee_id"] = eid if eid else None
        db_obj = self.model(**data)
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def reset_to_default_password(self, db: Session, *, db_obj: User) -> User:
        from app.schemas.auth import get_default_password
        db_obj.password = get_password_hash(get_default_password())
        db_obj.is_first_login = True
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj


crud_admin = CRUDAdmin(RecruitmentAdmin)
crud_user = CRUDUser(User)
