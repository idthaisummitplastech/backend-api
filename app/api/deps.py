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
                admin_id_val = int(admin_id_hdr)
            except (ValueError, TypeError):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Header X-Admin-Id tidak valid.")

            admin_found = crud_admin.get(db, admin_id_val)
            if not admin_found:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akun admin tidak ditemukan.")
            if hasattr(admin_found, "is_active") and getattr(admin_found, "is_active") is False:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akun dinonaktifkan.")
            if admin_role_hdr and admin_role_hdr.lower() != (admin_found.role or "").lower():
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Header role tidak sesuai dengan data akun.")
            return admin_found

        if admin_role_hdr:
            return RecruitmentAdmin(
                id=0,
                username="admin_internal",
                name="Internal Service Admin",
                role=admin_role_hdr.lower(),
                department=admin_dept_hdr,
                email="internal@system.local",
            )

        # Tanpa X-Admin-Id dan tanpa X-Admin-Role: tolak 403 (hapus fallback superadmin)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autentikasi internal memerlukan header X-Admin-Role atau X-Admin-Id.",
        )

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

    # Dependency guard: tolak token ber-scope terbatas di luar alur ganti password dan setup MFA
    if settings.FIRST_LOGIN_ENFORCE and payload.get("scope") == "first_login_setup":
        path = request.url.path if request else ""
        allowed_setup_prefixes = (
            "/api/v1/auth/mfa",
            "/api/v1/auth/cms-mfa",
            "/api/v1/auth/ats-mfa",
            "/api/v1/cms/profile",
            "/api/v1/auth/me/admin",
        )
        if not any(path.startswith(prefix) for prefix in allowed_setup_prefixes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Wajib mengganti kata sandi dan mengaktifkan MFA sebelum mengakses sistem",
            )

    # CAND-AUTH-01: Validasi tipe token eksplisit dan tolak token tanpa klaim type
    token_type = payload.get("type")
    if not token_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak memiliki klaim tipe atau berformat lama. Silakan login kembali.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if token_type == "applicant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Token sesi pelamar tidak memiliki wewenang akses administratif.",
        )

    if token_type not in ("ats", "cms"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tipe token otentikasi tidak dikenali.",
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

    if admin_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identitas subjek (ID) pada token tidak valid.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload_role = (payload.get("role") or "").lower()

    if token_type == "ats":
        admin = crud_admin.get(db, admin_id)
        if not admin:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Akun admin rekrutmen tidak ditemukan.",
            )
        if hasattr(admin, "is_active") and getattr(admin, "is_active") is False:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akun admin telah dinonaktifkan.")
        db_role = (admin.role or "").lower()
        if not payload_role or payload_role != db_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Wewenang (role) pada token tidak cocok dengan data akun pada basis data.",
            )
        return admin

    elif token_type == "cms":
        user = db.query(User).filter(User.id == admin_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Akun pengguna CMS tidak ditemukan.",
            )
        if hasattr(user, "is_active") and getattr(user, "is_active") is False:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akun pengguna telah dinonaktifkan.")
        db_role = (user.role or "").lower()
        if not payload_role or payload_role != db_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Wewenang (role) pada token tidak cocok dengan data akun pada basis data.",
            )
        return RecruitmentAdmin(
            id=user.id,
            username=user.username or user.email.split("@")[0],
            name=user.name,
            role=user.role,
            email=user.email,
            department=user.department,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Akun admin tidak terdaftar.",
    )



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

    # CAND-AUTH-01: Wajib klaim type=="applicant" dan role=="applicant"
    token_type = payload.get("type")
    token_role = payload.get("role")
    if token_type != "applicant" or token_role != "applicant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Token tidak valid untuk sesi pelamar.",
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
        admin_role = (current_admin.role or "").lower()
        if admin_role not in self.allowed_roles and admin_role not in ("admin", "superadmin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Akses Ditolak: Anda tidak memiliki izin untuk fitur ini. Wewenang dibutuhkan: {self.allowed_roles}",
            )
        return current_admin
