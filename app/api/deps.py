from typing import Any, Generator, List, Optional
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.session import get_db, get_db_company
from app.core.config import settings
from app.core.security import decode_access_token, verify_internal_api_secret
from app.crud.crud_auth import crud_admin
from app.crud.crud_recruitment import crud_applicant
from app.models.auth import RecruitmentAdmin, User
from app.models.recruitment import Applicant

# Standard Bearer scheme for Swagger UI & clients
security_scheme = HTTPBearer(auto_error=False)


def _header(request: Request, *names: str) -> Optional[str]:
    """Read the first present header (case-insensitive via Starlette)."""
    if not request or not hasattr(request, "headers"):
        return None
    for name in names:
        value = request.headers.get(name)
        if value:
            return value
    return None


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def require_account_identity(account, target_id: Any) -> None:
    """Anti-IDOR: memastikan target_id sama dengan id akun terautentikasi (Amandemen 2)."""
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autentikasi diperlukan.")
    account_id = getattr(account, "id", None)
    if account_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identitas akun tidak ditemukan.")
    # Akun sistem internal (id=0) diizinkan
    if account_id == 0:
        return
    if target_id is None:
        return
    try:
        t_id = int(target_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID target tidak valid.")
    if t_id != account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IDOR_DETECTED: Anda tidak berhak mengakses akun lain.",
        )


def _reject_stale_session(payload: dict, account) -> None:
    """
    Amandemen 7: tolak sesi yang diterbitkan sebelum password berubah / akun dipulihkan.
    Sesi lama tanpa klaim session_version diperlakukan sebagai versi 1. Setelah
    reset password menaikkan versi akun, token lama otomatis tidak berlaku.
    """
    token_version = payload.get("session_version", 1)
    account_version = getattr(account, "session_version", 1) or 1
    try:
        token_version = int(token_version)
    except (TypeError, ValueError):
        token_version = 0

    if token_version < account_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi telah dibatalkan karena perubahan kata sandi atau pemulihan akun. Silakan login kembali.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    changed_at = _as_utc(getattr(account, "password_changed_at", None))
    issued_at = payload.get("iat")
    if changed_at and isinstance(issued_at, (int, float)) and issued_at < changed_at.timestamp() - 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi telah dibatalkan karena kata sandi akun diubah. Silakan login kembali.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _extract_subject(payload: dict) -> int:
    sub_val = payload.get("sub")
    try:
        return int(sub_val)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identitas subjek (ID) pada token tidak valid.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _require_claims(payload: dict) -> None:
    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid atau telah kedaluwarsa.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not payload.get("type"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak memiliki klaim tipe atau berformat lama. Silakan login kembali.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _enforce_first_login_and_mfa(account, mfa_enabled_attr: str) -> None:
    """Aturan operasional Opsi A: akun wajib sudah ganti password dan MFA terverifikasi."""
    if not settings.FIRST_LOGIN_ENFORCE or getattr(account, "id", 0) == 0:
        return

    if getattr(account, "is_first_login", False) is True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FIRST_LOGIN_REQUIRED: Akun wajib mengganti kata sandi awal terlebih dahulu.",
        )

    if getattr(account, mfa_enabled_attr, False) is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA_SETUP_REQUIRED: Akun wajib mengaktifkan autentikasi dua faktor (MFA) terlebih dahulu.",
        )

    verified_at = _as_utc(getattr(account, "mfa_verified_at", None))
    if verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA_VERIFICATION_REQUIRED: Akun wajib memverifikasi kode MFA pada sesi login ini.",
        )

    session_age = (datetime.now(timezone.utc) - verified_at).total_seconds()
    if session_age > (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA_SESSION_EXPIRED: Sesi verifikasi MFA telah kedaluwarsa. Silakan verifikasi ulang kode TOTP.",
        )


def get_authenticated_admin_base(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> RecruitmentAdmin:
    """
    Dependensi Dasar ATS: Memvalidasi kredensial (internal secret + X-Admin-Id atau JWT ATS).
    TIDAK memeriksa is_first_login maupun kelengkapan MFA.
    Khusus digunakan pada endpoint alur pemenuhan kredensial (ganti password, setup/verify MFA).
    MENGABAIKAN header X-CMS-User-Id secara mutlak.
    """
    internal_key = _header(request, "x-internal-secret", "X-Internal-Secret")
    if internal_key:
        if not verify_internal_api_secret(internal_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak. Secret internal tidak valid.",
            )

        admin_id_hdr = _header(request, "x-admin-id", "X-Admin-Id")
        cms_id_hdr = _header(request, "x-cms-user-id", "X-CMS-User-Id")
        admin_role_hdr = _header(request, "x-admin-role", "X-Admin-Role")
        admin_dept_hdr = _header(request, "x-admin-department", "X-Admin-Department")

        if cms_id_hdr and not admin_id_hdr and not admin_role_hdr:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak. Header X-CMS-User-Id tidak berlaku pada layanan ATS.",
            )

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

            session_ver_hdr = _header(request, "x-session-version", "X-Session-Version")
            if session_ver_hdr is not None:
                try:
                    s_ver = int(session_ver_hdr)
                except (ValueError, TypeError):
                    s_ver = 0
                if s_ver < (getattr(admin_found, "session_version", 1) or 1):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Sesi telah dibatalkan karena perubahan kata sandi atau pemulihan akun. Silakan login kembali.",
                    )
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

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autentikasi internal ATS memerlukan header X-Admin-Role atau X-Admin-Id.",
        )

    # Bila dipanggil tanpa internal secret pada endpoint proxy internal ATS MFA
    try:
        url_obj = getattr(request, "url", None)
        raw_path = getattr(url_obj, "path", None)
    except Exception:
        raw_path = None

    if isinstance(raw_path, str) and (
        raw_path.startswith("/api/v1/auth/ats-mfa")
        or raw_path.startswith("/api/v1/auth/mfa")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Endpoint hanya dapat diakses melalui internal proxy.",
        )

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi diperlukan. Token tidak ditemukan.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    _require_claims(payload)

    token_type = payload.get("type")
    if token_type == "applicant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Token sesi pelamar tidak memiliki wewenang akses administratif.",
        )

    if token_type != "ats":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token sesi CMS tidak dapat digunakan pada layanan ATS.",
        )

    admin_id = _extract_subject(payload)
    admin = crud_admin.get(db, admin_id)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Akun admin rekrutmen tidak ditemukan.",
        )
    if hasattr(admin, "is_active") and getattr(admin, "is_active") is False:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akun admin telah dinonaktifkan.")

    payload_role = (payload.get("role") or "").lower()
    db_role = (admin.role or "").lower()
    if not payload_role or payload_role != db_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wewenang (role) pada token tidak cocok dengan data akun pada basis data.",
        )

    _reject_stale_session(payload, admin)
    return admin


def get_current_admin(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> RecruitmentAdmin:
    """
    Dependensi Operasional ATS: Memvalidasi identitas via get_authenticated_admin_base
    dan menegakkan aturan First-Login dan MFA Wajib (Opsi A) bila FIRST_LOGIN_ENFORCE aktif.
    """
    admin = get_authenticated_admin_base(request=request, credentials=credentials, db=db)

    # Penguatan 2: saat penegakan aktif, tolak akun sintetis role-only (id=0)
    # pada endpoint operasional — wajib X-Admin-Id dengan identitas nyata.
    if settings.FIRST_LOGIN_ENFORCE and getattr(admin, "id", None) == 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Penegakan first-login aktif: endpoint operasional ATS memerlukan header X-Admin-Id dengan identitas nyata.",
        )

    # Penguatan 1: saat FIRST_LOGIN_ENFORCE=true, header X-Session-Version WAJIB ada
    # untuk pemanggilan ber-X-Admin-Id; jika tidak ada, tolak 401.
    if settings.FIRST_LOGIN_ENFORCE and _header(request, "x-admin-id", "X-Admin-Id"):
        session_ver_hdr = _header(request, "x-session-version", "X-Session-Version")
        if session_ver_hdr is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Header X-Session-Version wajib disertakan saat penegakan first-login aktif.",
            )

    _enforce_first_login_and_mfa(admin, "is_mfa_enabled")
    return admin


def get_cms_user_base(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db_company: Session = Depends(get_db_company),
) -> User:
    """
    Dependensi Dasar CMS: Memvalidasi kredensial (internal secret + X-CMS-User-Id atau JWT CMS).
    TIDAK memeriksa is_first_login maupun mfa_enabled.
    Khusus digunakan pada endpoint alur pemenuhan kredensial CMS (ganti password, setup/verify MFA).
    MENGABAIKAN header X-Admin-Id secara mutlak.
    """
    internal_key = _header(request, "x-internal-secret", "X-Internal-Secret")
    if internal_key:
        if not verify_internal_api_secret(internal_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak. Secret internal tidak valid.",
            )

        cms_id_hdr = _header(request, "x-cms-user-id", "X-CMS-User-Id")
        admin_id_hdr = _header(request, "x-admin-id", "X-Admin-Id")
        admin_role_hdr = _header(request, "x-admin-role", "X-Admin-Role")
        admin_dept_hdr = _header(request, "x-admin-department", "X-Admin-Department")

        if admin_id_hdr and not cms_id_hdr and not admin_role_hdr:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak. Header X-Admin-Id tidak berlaku pada layanan CMS.",
            )

        if cms_id_hdr:
            try:
                cms_id_val = int(cms_id_hdr)
            except (ValueError, TypeError):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Header X-CMS-User-Id tidak valid.")

            user_found = db_company.query(User).filter(User.id == cms_id_val).first()
            if not user_found:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akun pengguna CMS tidak ditemukan.")
            if hasattr(user_found, "is_active") and getattr(user_found, "is_active") is False:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akun pengguna dinonaktifkan.")
            if admin_role_hdr and admin_role_hdr.lower() != (user_found.role or "").lower():
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Header role tidak sesuai dengan data akun.")

            session_ver_hdr = _header(request, "x-session-version", "X-Session-Version")
            if settings.FIRST_LOGIN_ENFORCE and session_ver_hdr is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Header X-Session-Version wajib disertakan saat penegakan first-login aktif.",
                )
            if session_ver_hdr is not None:
                try:
                    s_ver = int(session_ver_hdr)
                except (ValueError, TypeError):
                    s_ver = 0
                if s_ver < (getattr(user_found, "session_version", 1) or 1):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Sesi telah dibatalkan karena perubahan kata sandi atau pemulihan akun. Silakan login kembali.",
                    )
            return user_found

        if admin_role_hdr:
            return User(
                id=0,
                username="cms_internal",
                name="CMS Internal Service Admin",
                role=admin_role_hdr.lower(),
                department=admin_dept_hdr,
                email="cms_internal@system.local",
            )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Autentikasi internal CMS memerlukan header X-Admin-Role atau X-CMS-User-Id.",
        )

    try:
        url_obj = getattr(request, "url", None)
        raw_path = getattr(url_obj, "path", None)
    except Exception:
        raw_path = None

    if isinstance(raw_path, str) and raw_path.startswith("/api/v1/auth/cms-mfa"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Endpoint hanya dapat diakses melalui internal proxy.",
        )

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi diperlukan. Token tidak ditemukan.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    _require_claims(payload)

    if payload.get("type") != "cms":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token sesi ATS/Pelamar tidak dapat digunakan pada layanan CMS.",
        )

    user_id = _extract_subject(payload)
    user = db_company.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Akun pengguna CMS tidak ditemukan.",
        )
    if getattr(user, "is_active", True) is False:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akun pengguna telah dinonaktifkan.")

    payload_role = (payload.get("role") or "").lower()
    if not payload_role or payload_role != (user.role or "").lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wewenang (role) pada token tidak cocok dengan data akun pada basis data.",
        )

    _reject_stale_session(payload, user)
    return user


def get_current_cms_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db_company: Session = Depends(get_db_company),
) -> User:
    """
    Dependensi Operasional CMS: Memvalidasi identitas via get_cms_user_base
    dan menegakkan aturan First-Login dan MFA Wajib (Opsi A) bila FIRST_LOGIN_ENFORCE aktif.
    """
    user = get_cms_user_base(request=request, credentials=credentials, db_company=db_company)

    # Penguatan 2: saat penegakan aktif, tolak akun sintetis role-only (id=0)
    # pada endpoint operasional — wajib X-CMS-User-Id dengan identitas nyata.
    if settings.FIRST_LOGIN_ENFORCE and getattr(user, "id", None) == 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Penegakan first-login aktif: endpoint operasional CMS memerlukan header X-CMS-User-Id dengan identitas nyata.",
        )

    # Penguatan 1: saat FIRST_LOGIN_ENFORCE=true, header X-Session-Version WAJIB ada
    # untuk pemanggilan ber-X-CMS-User-Id; jika tidak ada, tolak 401.
    if settings.FIRST_LOGIN_ENFORCE and _header(request, "x-cms-user-id", "X-CMS-User-Id"):
        session_ver_hdr = _header(request, "x-session-version", "X-Session-Version")
        if session_ver_hdr is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Header X-Session-Version wajib disertakan saat penegakan first-login aktif.",
            )

    _enforce_first_login_and_mfa(user, "mfa_enabled")
    return user


def get_current_applicant(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> Applicant:
    """Validate Bearer JWT or internal service secret + applicant ID."""
    internal_key = _header(request, "x-internal-secret", "X-Internal-Secret")
    if internal_key and verify_internal_api_secret(internal_key):
        app_id_str = _header(request, "x-applicant-id", "X-Applicant-Id")
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
