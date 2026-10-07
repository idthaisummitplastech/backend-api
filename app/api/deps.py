from typing import Generator, List, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import settings
from app.core.security import decode_access_token
from app.crud.crud_auth import crud_admin
from app.crud.crud_recruitment import crud_applicant
from app.models.auth import RecruitmentAdmin, User
from app.models.recruitment import Applicant

# Standard Bearer scheme for Swagger UI & clients
security_scheme = HTTPBearer(auto_error=False)


def get_current_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> RecruitmentAdmin:
    """Validate Bearer JWT or internal service secret and retrieve authenticated Admin / HR entity."""
    # 1. Allow internal service communication from Next.js server actions
    internal_key = request.headers.get("x-internal-secret") or request.headers.get("X-Internal-Secret")
    if internal_key and internal_key == settings.SECRET_KEY:
        admin_id_hdr = request.headers.get("x-admin-id") or request.headers.get("X-Admin-Id")
        admin_role_hdr = request.headers.get("x-admin-role") or request.headers.get("X-Admin-Role")
        admin_dept_hdr = request.headers.get("x-admin-department") or request.headers.get("X-Admin-Department")

        if admin_id_hdr:
            try:
                admin_found = crud_admin.get(db, int(admin_id_hdr))
                if admin_found:
                    # hormati is_active jika ada
                    if hasattr(admin_found, "is_active") and getattr(admin_found, "is_active") is False:
                        raise HTTPException(status_code=403, detail="Account deactivated.")
                    return admin_found
            except (ValueError, TypeError):
                pass
            except HTTPException:
                raise

        if admin_role_hdr:
            return RecruitmentAdmin(
                id=int(admin_id_hdr) if admin_id_hdr and admin_id_hdr.isdigit() else 1,
                username="admin_internal",
                name="Internal Service Admin",
                role=admin_role_hdr.lower(),
                department=admin_dept_hdr,
                email="admin@itsp.co.id",
            )

        admin = crud_admin.get_by_username(db, "admin")
        if admin:
            return admin
        return RecruitmentAdmin(id=1, username="admin", name="Administrator", role="admin", email="admin@itsp.co.id")

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi diperlukan. Token tidak ditemukan.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid atau telah kedaluwarsa.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub_val = payload["sub"]
    admin_id = None
    if isinstance(sub_val, int):
        admin_id = sub_val
    elif isinstance(sub_val, str):
        if sub_val.isdigit():
            admin_id = int(sub_val)
        elif sub_val.startswith("{"):
            try:
                import ast
                parsed = ast.literal_eval(sub_val)
                if isinstance(parsed, dict):
                    raw_id = parsed.get("sub") or parsed.get("id")
                    if raw_id and str(raw_id).isdigit():
                        admin_id = int(raw_id)
            except Exception:
                pass

    admin = None
    if admin_id is not None:
        admin = crud_admin.get(db, admin_id)
        if not admin:
            # Check User table in web_perusahaan
            user = db.query(User).filter(User.id == admin_id).first()
            if user:
                admin = RecruitmentAdmin(
                    id=user.id,
                    username=user.username or user.email.split("@")[0],
                    name=user.name,
                    role=user.role,
                    email=user.email,
                    department=user.department,
                )

    if not admin and payload.get("email"):
        admin = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(payload.get("email"))).first()
        if not admin:
            user = db.query(User).filter(User.email.ilike(payload.get("email"))).first()
            if user:
                admin = RecruitmentAdmin(
                    id=user.id,
                    username=user.username or user.email.split("@")[0],
                    name=user.name,
                    role=user.role,
                    email=user.email,
                    department=user.department,
                )

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Akun admin tidak terdaftar.",
        )

    return admin



def get_current_applicant(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> Applicant:
    """Validate Bearer JWT or internal service secret + applicant ID."""
    internal_key = request.headers.get("x-internal-secret") or request.headers.get("X-Internal-Secret")
    if internal_key and internal_key == settings.SECRET_KEY:
        app_id_str = request.headers.get("x-applicant-id") or request.headers.get("X-Applicant-Id")
        if app_id_str:
            try:
                applicant = crud_applicant.get(db, int(app_id_str))
                if applicant:
                    return applicant
            except (ValueError, TypeError):
                pass

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi pelamar diperlukan. Silakan login terlebih dahulu.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sesi pelamar tidak valid.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub_val = payload["sub"]
    applicant_id = None
    if isinstance(sub_val, int):
        applicant_id = sub_val
    elif isinstance(sub_val, str) and sub_val.isdigit():
        applicant_id = int(sub_val)

    applicant = crud_applicant.get(db, applicant_id) if applicant_id else None
    if not applicant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Akun pelamar tidak ditemukan.",
        )

    return applicant


class RoleChecker:
    """
    Reusable OOP Dependency for Role-Based Access Control (RBAC).
    Usage: Depends(RoleChecker(["admin", "hr"]))
    """

    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = [r.lower() for r in allowed_roles]

    def __call__(self, current_admin: RecruitmentAdmin = Depends(get_current_admin)) -> RecruitmentAdmin:
        if current_admin.role.lower() not in self.allowed_roles and current_admin.role.lower() != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Akses Ditolak: Anda tidak memiliki izin untuk fitur ini. Wewenang dibutuhkan: {self.allowed_roles}",
            )
        return current_admin
