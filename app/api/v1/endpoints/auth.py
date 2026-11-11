import json
import secrets
from typing import Any, Dict
import time
from datetime import datetime, timezone, timedelta
import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db, get_db_company
from app.schemas.auth import (
    LoginRequest,
    ApplicantLoginRequest,
    Token,
    MFASetupResponse,
    MFAVerifyRequest,
    AdminResponse,
)
from app.schemas.common import ApiResponse
from app.services.auth_service import auth_service
from app.api.deps import (
    get_current_admin,
    get_authenticated_admin_base,
    get_current_applicant,
    get_cms_user_base,
    require_account_identity,
)
from app.models.auth import RecruitmentAdmin, User
from app.models.recruitment import Applicant
from app.core.middleware import limiter
from app.core.security import verify_password, create_access_token, verify_internal_api_secret
from app.core.config import settings

router = APIRouter()


def require_internal_secret(request: Request) -> None:
    """Validasi secret komunikasi internal proxy Next.js. Tolak pemanggilan langsung dari internet."""
    internal_key = request.headers.get("x-internal-secret") or request.headers.get("X-Internal-Secret")
    if not verify_internal_api_secret(internal_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Endpoint hanya dapat diakses melalui internal proxy.",
        )


@router.post("/cms-login")
@limiter.limit("15/minute")
def login_cms_user(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db_company),
):
    """CMS Admin authentication — Employee ID primary (004.02.16) dual-mode fallback email/username, hormati is_active & portal_access."""
    raw_id = str(payload.get("employee_id", "") or payload.get("employee_id_or_email", "") or payload.get("email", "") or payload.get("username", "") or payload.get("login", "")).strip()
    password = str(payload.get("password", ""))
    if not raw_id or not password:
        raise HTTPException(status_code=400, detail="Employee ID / Email and password are required.")
    # Dual-mode: employee_id exact -> username ilike -> email ilike
    user = None
    if raw_id:
        try:
            user = db.query(User).filter(User.employee_id == raw_id).first()
        except Exception:
            user = None
    if not user:
        # try username exact lower
        try:
            user = db.query(User).filter(User.username.ilike(raw_id)).first()
        except Exception:
            user = None
    if not user:
        user = db.query(User).filter(User.email.ilike(raw_id.strip().lower())).first()
        # also handle bare username -> try email with @itsp.co.id
        if not user and "@" not in raw_id:
            user = db.query(User).filter(User.email.ilike(f"{raw_id.lower()}@itsp.co.id")).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Invalid Employee ID / Email or password.")
    # resign guard via employee_id -> DataKaryawan (if same DB, else skip gracefully)
    try:
        eid = getattr(user, "employee_id", None)
        if eid:
            from app.models.recruitment import DataKaryawan
            # only if DataKaryawan table exists in this DB (web_perusahaan separate) try company DB? try get_db mapping
            # attempt to query via current db (may be empty) - safe to skip if table not in this engine
            dk = db.query(DataKaryawan).filter(DataKaryawan.employee_id == eid).first() if hasattr(DataKaryawan, "employee_id") else None
            if dk and getattr(dk, "employee_status", None) == "resign":
                raise HTTPException(status_code=403, detail="Akun karyawan sudah resign — akses ditolak. Hubungi HR.")
    except HTTPException:
        raise
    except Exception:
        pass

    # Active toggle — if deactivated, deny login on all portals
    if hasattr(user, "is_active") and getattr(user, "is_active") is False:
        raise HTTPException(status_code=403, detail="Your account has been deactivated by the Administrator. Please contact admin to reactivate.")

    # Portal access — cms-login only for Company Website
    pa = getattr(user, "portal_access", "both") or "both"
    if pa not in ("perusahaan", "both"):
        raise HTTPException(status_code=403, detail="Your account does not have access to the Company Website. Please ask admin to set portal_access to Company or Both.")

    is_first = bool(getattr(user, "is_first_login", False))
    admin_roles = ["admin", "hr", "user_dept", "marketing"]
    mfa_pending = (user.role in admin_roles and not user.mfa_enabled)
    token_scope = "first_login_setup" if (settings.FIRST_LOGIN_ENFORCE and (is_first or mfa_pending)) else None

    token = create_access_token(
        subject=str(user.id),
        role=user.role,
        department=getattr(user, "department", None),
        extra_claims={
            "email": user.email,
            "name": user.name,
            "employee_id": getattr(user, "employee_id", None),
            "type": "cms",
        },
        scope=token_scope,
    )
    has_secret = bool(user.mfa_secret)
    return {
        "success": True,
        "token": token,
        "user": {
            "id": user.id,
            "employee_id": getattr(user, "employee_id", None),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "mfa_enabled": user.mfa_enabled,
            "has_mfa_secret": has_secret,
            "is_first_login": getattr(user, "is_first_login", False),
        },
        "requires_mfa": user.mfa_enabled,
        "has_mfa_secret": has_secret,
        "is_first_login": getattr(user, "is_first_login", False),
    }


@router.post("/ats-login")
@limiter.limit("30/minute")
def login_ats_admin(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    db_company: Session = Depends(get_db_company),
):
    """
    Unified ATS Admin login:
    1. Check central CMS users (web_perusahaan) first (case-insensitive)
    2. Fallback to local recruitment_admins (web_karir)
    3. Handle MFA setup/verify and bidirectional sync without database constraint errors
    """
    try:
        # Employee ID primary (004.02.16) dual-mode fallback username/email
        raw_identifier = str(payload.get("employee_id", "") or payload.get("employee_id_or_email", "") or payload.get("login", "") or payload.get("username", "") or payload.get("email", "")).strip()
        password = str(payload.get("password", ""))
        mfa_code = str(payload.get("mfa_code") or payload.get("mfaCode", "")).strip()
        username = raw_identifier  # keep legacy variable name for downstream logic

        if not raw_identifier or not password:
            raise HTTPException(status_code=400, detail="Employee ID / Username / Email and password are required.")

        # Employee ID exact lookup priority before email/username normalization
        # If raw looks like employee_id (contains dot), keep case exact for employee_id queries
        clean_input = raw_identifier.lower()
        if clean_input.endswith("@itsp.com"):
            clean_input = clean_input.replace("@itsp.com", "@itsp.co.id")

        # Fast path: try employee_id exact on CMS users and local admins
        cms_by_eid = None
        local_by_eid = None
        try:
            cms_by_eid = db_company.query(User).filter(User.employee_id == raw_identifier).first()
        except Exception:
            cms_by_eid = None
        try:
            local_by_eid = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.employee_id == raw_identifier).first()
        except Exception:
            local_by_eid = None

        # 1. Check central CMS users (web_perusahaan) — employee_id first
        cms_user = cms_by_eid
        if not cms_user:
            target_email = clean_input if "@" in clean_input else f"{clean_input}@itsp.co.id"
            cms_user = db_company.query(User).filter(User.email.ilike(target_email)).first()

        if not cms_user and "@" not in clean_input:
            cms_user = db_company.query(User).filter(User.email.ilike(clean_input)).first()

        # Check by User.username if present
        if not cms_user and "@" not in clean_input:
            cms_user = db_company.query(User).filter(User.username.ilike(clean_input)).first()

        # Check if username matches split email or recruitment_admin username
        if not cms_user and "@" not in clean_input:
            ra_probe = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.username.ilike(clean_input)).first()
            if ra_probe and ra_probe.email:
                cms_user = db_company.query(User).filter(User.email.ilike(ra_probe.email)).first()

        if cms_user:
            # Check password against CMS user, fallback to recruitment_admin password if needed
            is_pwd_valid = verify_password(password, cms_user.password)
            if not is_pwd_valid:
                ra_probe = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(cms_user.email)).first()
                if ra_probe and verify_password(password, ra_probe.password):
                    is_pwd_valid = True
                    cms_user.password = ra_probe.password
                    try:
                        db_company.commit()
                    except Exception:
                        db_company.rollback()

            if not is_pwd_valid:
                raise HTTPException(status_code=401, detail="Password salah. Silakan coba kembali.")

            # RBAC + portal active check for ATS
            if hasattr(cms_user, "is_active") and getattr(cms_user, "is_active") is False:
                raise HTTPException(status_code=403, detail="Your account has been deactivated by the Administrator.")
            pa_cms = getattr(cms_user, "portal_access", "both") or "both"
            if pa_cms not in ("karir", "both"):
                raise HTTPException(status_code=403, detail="Your account does not have access to the Career Portal. Please ask admin to set portal_access to Career or Both.")
            allowed_roles = ["admin", "hr", "user_dept"]
            if cms_user.role == "marketing":
                raise HTTPException(status_code=403, detail="Akses Ditolak: Akun Tim Marketing tidak memiliki hak akses ke Portal Karir & Rekrutmen ATS.")
            if cms_user.role not in allowed_roles:
                raise HTTPException(status_code=403, detail=f"Akses Ditolak: Role '{cms_user.role}' belum diberikan izin ke portal ini.")

            # MFA Setup & Verification
            if not cms_user.mfa_enabled or not cms_user.mfa_secret:
                secret = cms_user.mfa_secret
                if not secret:
                    secret = pyotp.random_base32()
                    cms_user.mfa_secret = secret
                    try:
                        db_company.commit()
                    except Exception:
                        db_company.rollback()

                if not mfa_code:
                    totp_uri = f"otpauth://totp/PT%20ITSP%20ATS:{cms_user.email}?secret={secret}&issuer=PT%20ITSP%20ATS&algorithm=SHA1&digits=6&period=30"
                    return {
                        "require_mfa_setup": True,
                        "secret": secret,
                        "totp_uri": totp_uri,
                        "email": cms_user.email,
                        "username": cms_user.email.split("@")[0],
                        "name": cms_user.name,
                        "message": "Akun Anda diwajibkan mengaktifkan Google Authenticator.",
                    }

                totp = pyotp.TOTP(secret)
                is_dev_bypass = settings.ENVIRONMENT == "development" and mfa_code in ["123456", "000000"]
                if not is_dev_bypass and not totp.verify(mfa_code, valid_window=30):
                    raise HTTPException(
                        status_code=401,
                        detail="Kode verifikasi 6-digit tidak valid atau sudah kedaluwarsa. Pastikan jam pada smartphone Anda sesuai (Automatic Date & Time).",
                    )

                cms_user.mfa_enabled = True
                try:
                    db_company.commit()
                except Exception:
                    db_company.rollback()
            else:
                if not mfa_code:
                    return {
                        "require_mfa": True,
                        "message": "Akun dilindungi MFA. Masukkan 6-digit kode Authenticator.",
                    }

                totp = pyotp.TOTP(cms_user.mfa_secret)
                is_valid = (settings.ENVIRONMENT == "development" and mfa_code in ["123456", "000000"]) or totp.verify(mfa_code, valid_window=30)

                # Fallback: check against recruitment_admins secret
                if not is_valid:
                    ats_probe = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(cms_user.email)).first()
                    if ats_probe and ats_probe.mfa_secret:
                        totp2 = pyotp.TOTP(ats_probe.mfa_secret)
                        if totp2.verify(mfa_code, valid_window=30):
                            is_valid = True
                            cms_user.mfa_secret = ats_probe.mfa_secret
                            cms_user.mfa_enabled = True
                            try:
                                db_company.commit()
                            except Exception:
                                db_company.rollback()

                # Fallback: check backup codes
                if not is_valid and cms_user.backup_codes:
                    try:
                        backup_list = json.loads(cms_user.backup_codes) if isinstance(cms_user.backup_codes, str) else cms_user.backup_codes
                        clean_code = mfa_code.upper().replace("-", "").replace(" ", "")
                        for i, bc in enumerate(backup_list):
                            if bc.replace("-", "").upper() == clean_code:
                                is_valid = True
                                backup_list.pop(i)
                                cms_user.backup_codes = json.dumps(backup_list)
                                db_company.commit()
                                break
                    except Exception:
                        pass

                if not is_valid:
                    raise HTTPException(
                        status_code=401,
                        detail="Kode MFA 6-digit tidak valid atau sudah kedaluwarsa. Periksa kembali kode di aplikasi Google Authenticator.",
                    )

            # Determine department
            dept_map = {"hr": "Human Capital", "user_dept": "Engineering", "admin": "IT & Systems"}
            dept_name = dept_map.get(cms_user.role, "General Management")

            # Safe bidirectional sync to recruitment_admins in Career DB
            ats_admin = db.query(RecruitmentAdmin).filter(
                (RecruitmentAdmin.email.ilike(cms_user.email)) |
                (RecruitmentAdmin.username.ilike(cms_user.email.split("@")[0]))
            ).first()

            try:
                if ats_admin:
                    ats_admin.name = cms_user.name
                    ats_admin.role = cms_user.role
                    ats_admin.department = ats_admin.department or dept_name
                    ats_admin.is_mfa_enabled = True
                    ats_admin.mfa_secret = cms_user.mfa_secret
                    ats_admin.password = cms_user.password
                    db.commit()
                else:
                    base_username = cms_user.email.split("@")[0]
                    username_candidate = base_username
                    counter = 1
                    while db.query(RecruitmentAdmin).filter(RecruitmentAdmin.username.ilike(username_candidate)).first():
                        username_candidate = f"{base_username}{counter}"
                        counter += 1

                    ats_admin = RecruitmentAdmin(
                        username=username_candidate,
                        email=cms_user.email.lower(),
                        password=cms_user.password,
                        name=cms_user.name,
                        role=cms_user.role,
                        department=dept_name,
                        is_mfa_enabled=True,
                        mfa_secret=cms_user.mfa_secret,
                    )
                    db.add(ats_admin)
                    db.commit()
                    db.refresh(ats_admin)
            except Exception:
                db.rollback()
                ats_admin = db.query(RecruitmentAdmin).filter(
                    (RecruitmentAdmin.email.ilike(cms_user.email)) |
                    (RecruitmentAdmin.username.ilike(cms_user.email.split("@")[0]))
                ).first()

            admin_id = ats_admin.id if ats_admin else cms_user.id
            admin_username = ats_admin.username if ats_admin else cms_user.email.split("@")[0]
            admin_name = cms_user.name
            admin_role = cms_user.role
            admin_dept = (ats_admin.department if ats_admin else None) or dept_name

            is_first = bool(getattr(cms_user, "is_first_login", False) or (ats_admin and getattr(ats_admin, "is_first_login", False)))
            admin_roles = ["admin", "hr", "user_dept", "marketing"]
            mfa_pending = (admin_role in admin_roles and not cms_user.mfa_enabled)
            token_scope = "first_login_setup" if (settings.FIRST_LOGIN_ENFORCE and (is_first or mfa_pending)) else None

            token = create_access_token(
                subject=str(admin_id),
                role=admin_role,
                department=admin_dept,
                extra_claims={"email": cms_user.email, "name": admin_name, "type": "ats"},
                scope=token_scope,
            )

            return {
                "success": True,
                "source": "central_cms_users",
                "token": token,
                "admin": {
                    "id": admin_id,
                    "username": admin_username,
                    "name": admin_name,
                    "email": cms_user.email,
                    "role": admin_role,
                    "department": admin_dept,
                    "is_mfa_enabled": True,
                    "is_first_login": is_first,
                },
            }

        # 2. Fallback to local recruitment_admins (web_karir) — employee_id first
        local_admin = local_by_eid
        if not local_admin:
            local_admin = db.query(RecruitmentAdmin).filter(
                (RecruitmentAdmin.username.ilike(clean_input)) | (RecruitmentAdmin.email.ilike(clean_input))
            ).first()
            if not local_admin and "@" not in clean_input:
                # also try exact employee_id case (already done) but safe retry
                try:
                    local_admin = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.employee_id == raw_identifier).first()
                except Exception:
                    pass

        if not local_admin:
            raise HTTPException(status_code=401, detail="Kredensial login tidak ditemukan. Periksa kembali username/email Anda.")

        if not verify_password(password, local_admin.password):
            raise HTTPException(status_code=401, detail="Password salah. Silakan coba kembali.")

        if hasattr(local_admin, "is_active") and getattr(local_admin, "is_active") is False:
            raise HTTPException(status_code=403, detail="Your account has been deactivated by the Administrator.")
        pa_local = getattr(local_admin, "portal_access", "both") or "both"
        if pa_local not in ("karir", "both"):
            raise HTTPException(status_code=403, detail="Your account does not have access to the Career Portal. Please ask admin to set portal_access to Career or Both.")

        # MFA for local admin
        if not local_admin.is_mfa_enabled or not local_admin.mfa_secret:
            secret = local_admin.mfa_secret
            if not secret:
                secret = pyotp.random_base32()
                local_admin.mfa_secret = secret
                try:
                    db.commit()
                except Exception:
                    db.rollback()

            if not mfa_code:
                totp_uri = f"otpauth://totp/PT%20ITSP%20ATS:{local_admin.username}?secret={secret}&issuer=PT%20ITSP%20ATS&algorithm=SHA1&digits=6&period=30"
                return {
                    "require_mfa_setup": True,
                    "secret": secret,
                    "totp_uri": totp_uri,
                    "email": local_admin.email,
                    "username": local_admin.username,
                    "name": local_admin.name,
                    "message": "Akun Anda diwajibkan mengaktifkan Google Authenticator.",
                }

            totp = pyotp.TOTP(secret)
            is_dev_bypass = settings.ENVIRONMENT == "development" and mfa_code in ["123456", "000000"]
            if not is_dev_bypass and not totp.verify(mfa_code, valid_window=30):
                raise HTTPException(
                    status_code=401,
                    detail="Kode MFA 6-digit tidak valid atau sudah kedaluwarsa. Pastikan jam pada smartphone Anda sesuai.",
                )

            local_admin.is_mfa_enabled = True
            try:
                db.commit()
            except Exception:
                db.rollback()

            # Sync MFA state to db_company (CMS User)
            try:
                cu = db_company.query(User).filter(User.email.ilike(local_admin.email)).first()
                if cu:
                    cu.mfa_enabled = True
                    cu.mfa_secret = local_admin.mfa_secret
                    db_company.commit()
            except Exception:
                db_company.rollback()
        else:
            if not mfa_code:
                return {
                    "require_mfa": True,
                    "message": "Akun dilindungi MFA. Masukkan 6-digit kode Authenticator.",
                }

            totp = pyotp.TOTP(local_admin.mfa_secret)
            is_dev_bypass = settings.ENVIRONMENT == "development" and mfa_code in ["123456", "000000"]
            if not is_dev_bypass and not totp.verify(mfa_code, valid_window=30):
                raise HTTPException(
                    status_code=401,
                    detail="Kode MFA 6-digit tidak valid atau sudah kedaluwarsa.",
                )

        is_first = bool(getattr(local_admin, "is_first_login", False))
        admin_roles = ["admin", "hr", "user_dept", "marketing"]
        mfa_pending = (local_admin.role in admin_roles and not local_admin.is_mfa_enabled)
        token_scope = "first_login_setup" if (settings.FIRST_LOGIN_ENFORCE and (is_first or mfa_pending)) else None

        token = create_access_token(
            subject=str(local_admin.id),
            role=local_admin.role,
            department=local_admin.department,
            extra_claims={"email": local_admin.email, "name": local_admin.name, "type": "ats"},
            scope=token_scope,
        )

        return {
            "success": True,
            "source": "local_recruitment_admins",
            "token": token,
            "admin": {
                "id": local_admin.id,
                "username": local_admin.username,
                "name": local_admin.name,
                "email": local_admin.email,
                "role": local_admin.role,
                "department": local_admin.department,
                "is_mfa_enabled": True,
                "is_first_login": is_first,
            },
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Unhandled error in login_ats_admin: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Terjadi kendala pada server saat memproses login/MFA: {str(exc)}",
        )


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login_admin(

    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    """Admin & Evaluator authentication — Employee ID primary (004.02.16) dual-mode fallback."""
    identifier = getattr(payload, "login_identifier", None) or payload.username_or_email
    if callable(identifier):
        identifier = identifier  # shouldn't happen
    # login_identifier is property, so call str
    try:
        identifier = payload.login_identifier
    except Exception:
        identifier = payload.username_or_email
    return auth_service.authenticate_admin(
        db,
        username_or_email=identifier,
        password=payload.password,
        totp_code=payload.totp_code,
    )


@router.post("/applicant-login", response_model=Token)
@limiter.limit("15/minute")
def login_applicant(
    request: Request,
    payload: ApplicantLoginRequest,
    db: Session = Depends(get_db),
):
    """Career portal candidate login."""
    return auth_service.authenticate_applicant(
        db, email=payload.email, password=payload.password
    )


@router.get("/me/admin", response_model=ApiResponse[AdminResponse])
def get_current_admin_profile(
    current_admin: RecruitmentAdmin = Depends(get_current_admin),
):
    """Retrieve authenticated admin details."""
    return ApiResponse(data=AdminResponse.model_validate(current_admin))


@router.get("/me/applicant")
def get_current_applicant_profile(
    current_applicant: Applicant = Depends(get_current_applicant),
):
    """Retrieve authenticated applicant overview."""
    return {
        "id": current_applicant.id,
        "full_name": current_applicant.full_name,
        "email": current_applicant.email,
        "current_stage": current_applicant.current_stage,
        "stage_status": current_applicant.stage_status,
        "created_at": current_applicant.created_at,
    }


@router.post("/mfa/setup", response_model=ApiResponse[MFASetupResponse])
def setup_mfa(
    current_admin: RecruitmentAdmin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Generate 2FA TOTP secret and QR URI."""
    if getattr(current_admin, "is_mfa_enabled", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA sudah aktif. Setup ulang tidak diizinkan.",
        )
    result = auth_service.setup_admin_mfa(db, current_admin.id)
    return ApiResponse(data=MFASetupResponse(**result))


@router.post("/mfa/verify", response_model=ApiResponse[bool])
def verify_mfa(
    payload: MFAVerifyRequest,
    current_admin: RecruitmentAdmin = Depends(get_current_admin),
    db: Session = Depends(get_db),
    db_company: Session = Depends(get_db_company),
):
    """Verify code and formally activate MFA on admin account across both databases."""
    success = auth_service.verify_and_enable_mfa(db, current_admin.id, payload.code)
    if success:
        try:
            cu = db_company.query(User).filter(User.email.ilike(current_admin.email)).first()
            if cu:
                cu.mfa_enabled = True
                cu.mfa_secret = current_admin.mfa_secret
                db_company.commit()
        except Exception:
            db_company.rollback()
    return ApiResponse(data=success, message="Two-factor MFA successfully enabled.")


# --- CMS ADMIN MFA ENDPOINTS (Company Profile) ---
@router.get("/cms-mfa/{user_id}")
def get_cms_user_mfa(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db_company),
    current_user: User = Depends(get_cms_user_base),
):
    """Retrieve CMS user MFA configuration. Identitas hanya dari X-CMS-User-Id/JWT CMS."""
    require_internal_secret(request)
    if not isinstance(current_user, User):
        user = db.query(User).filter(User.id == user_id).first()
    else:
        user = current_user
    if not user:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
    require_account_identity(user, user_id)

    backup_codes_count = 0
    if user.backup_codes:
        try:
            backup_codes_count = len(json.loads(user.backup_codes))
        except Exception:
            pass

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "mfa_enabled": bool(user.mfa_enabled),
        # Secret hanya dikembalikan saat setup awal (mfa_enabled=False). Setelah aktif, dilarang bocor.
        "mfa_secret": user.mfa_secret if not user.mfa_enabled else None,
        "backup_codes_count": backup_codes_count,
    }


@router.put("/cms-mfa/{user_id}/save-secret")
def save_cms_mfa_secret(
    user_id: int,
    payload: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db_company),
    current_user: User = Depends(get_cms_user_base),
):
    """Save generated MFA secret for CMS user before activation."""
    require_internal_secret(request)
    if not isinstance(current_user, User):
        user = db.query(User).filter(User.id == user_id).first()
    else:
        user = current_user
    if not user:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
    require_account_identity(user, user_id)

    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA sudah aktif. Secret tidak dapat diubah.")

    secret = payload.get("secret")
    if secret:
        user.mfa_secret = secret
        db.commit()
    return {"success": True, "secret": user.mfa_secret}


@router.post("/cms-mfa/activate")
def activate_cms_mfa(
    payload: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db_company),
    current_user: User = Depends(get_cms_user_base),
):
    """Activate MFA for CMS user after code verification."""
    require_internal_secret(request)
    target_id_raw = payload.get("user_id") or payload.get("userId")
    if not target_id_raw:
        raise HTTPException(status_code=400, detail="ID pengguna (user_id) wajib disertakan.")

    if not isinstance(current_user, User):
        user = db.query(User).filter(User.id == int(target_id_raw)).first() if target_id_raw else None
    else:
        user = current_user
    if not user:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
    require_account_identity(user, target_id_raw)

    secret = payload.get("secret")
    backup_codes = payload.get("backup_codes") or payload.get("backupCodes")

    if user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA sudah aktif pada akun ini.")

    now_utc = datetime.now(timezone.utc)
    user.mfa_enabled = True
    user.mfa_verified_at = now_utc
    if secret:
        user.mfa_secret = secret
    if backup_codes:
        user.backup_codes = backup_codes if isinstance(backup_codes, str) else json.dumps(backup_codes)
    db.commit()

    # Sync MFA secret and enabled status to RecruitmentAdmin in web_karir
    try:
        from app.db.session import SessionLocal
        with SessionLocal() as karir_db:
            rec_admin = karir_db.query(RecruitmentAdmin).filter(RecruitmentAdmin.email.ilike(user.email)).first()
            if rec_admin:
                rec_admin.is_mfa_enabled = True
                rec_admin.mfa_verified_at = now_utc
                if secret:
                    rec_admin.mfa_secret = secret
                karir_db.commit()
    except Exception:
        pass

    return {
        "success": True,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
        }
    }


@router.post("/cms-mfa/verify")
def verify_cms_mfa(
    payload: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db_company),
    current_user: User = Depends(get_cms_user_base),
):
    """Verify MFA code or backup code for CMS user login."""
    require_internal_secret(request)
    target_id_raw = payload.get("user_id") or payload.get("userId")
    if not target_id_raw:
        raise HTTPException(status_code=400, detail="User ID wajib disertakan.")

    user = db.query(User).filter(User.id == int(target_id_raw)).first()
    if not user or not user.mfa_secret:
        raise HTTPException(status_code=400, detail="Konfigurasi MFA pengguna tidak valid.")
    if isinstance(current_user, User) and current_user.id != 0:
        require_account_identity(current_user, target_id_raw)

    now_utc = datetime.now(timezone.utc)
    if user.totp_locked_until:
        locked_until = user.totp_locked_until if user.totp_locked_until.tzinfo else user.totp_locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now_utc:
            remaining = int((locked_until - now_utc).total_seconds())
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Akun terkunci sementara karena terlalu banyak percobaan salah. Coba lagi dalam {remaining} detik.",
            )

    code = str(payload.get("code", "")).strip().replace(" ", "")
    current_timestep = int(time.time() / 30)

    # Anti-replay check
    if getattr(user, "last_used_totp_timestep", None) == current_timestep:
        raise HTTPException(status_code=400, detail="Kode TOTP telah digunakan. Tunggu kode berikutnya (30 detik).")

    totp = pyotp.TOTP(user.mfa_secret)
    is_valid = totp.verify(code, valid_window=1)
    used_backup = False

    if not is_valid and user.backup_codes:
        try:
            backup_list = json.loads(user.backup_codes)
            upper_code = code.upper()
            if upper_code in backup_list:
                is_valid = True
                used_backup = True
                backup_list.remove(upper_code)
                user.backup_codes = json.dumps(backup_list)
                db.commit()
        except Exception:
            pass

    if not is_valid:
        user.totp_failed_attempts = getattr(user, "totp_failed_attempts", 0) + 1
        if user.totp_failed_attempts >= 5:
            user.totp_locked_until = now_utc + timedelta(minutes=15)
        db.commit()
        raise HTTPException(status_code=400, detail="Kode autentikasi salah atau sudah kedaluwarsa.")

    user.totp_failed_attempts = 0
    user.totp_locked_until = None
    if not used_backup:
        user.last_used_totp_timestep = current_timestep
    user.mfa_verified_at = now_utc
    db.commit()

    return {
        "success": True,
        "used_backup": used_backup,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
        }
    }


# --- ATS ADMIN MFA ENDPOINTS ---
@router.get("/ats-mfa/{admin_id}/setup")
def get_ats_admin_mfa_setup(
    admin_id: int,
    request: Request,
    db: Session = Depends(get_db),
    db_company: Session = Depends(get_db_company),
    current_admin: RecruitmentAdmin = Depends(get_authenticated_admin_base),
):
    """Retrieve or initialize MFA TOTP secret for ATS Admin."""
    require_internal_secret(request)
    if not isinstance(current_admin, RecruitmentAdmin):
        admin = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == admin_id).first()
    else:
        admin = current_admin
    if not admin:
        raise HTTPException(status_code=404, detail="Admin rekrutmen tidak ditemukan.")
    require_account_identity(admin, admin_id)

    if admin.is_mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA sudah aktif. Setup ulang tidak diizinkan.")

    secret = admin.mfa_secret
    if not secret:
        secret = pyotp.random_base32()
        admin.mfa_secret = secret
        db.commit()

        cms_user = db_company.query(User).filter(User.email == admin.email).first()
        if cms_user:
            cms_user.mfa_secret = secret
            db_company.commit()

    totp_uri = f"otpauth://totp/PT%20ITSP%20ATS:{admin.username}?secret={secret}&issuer=PT%20ITSP%20ATS&algorithm=SHA1&digits=6&period=30"

    return {
        "success": True,
        "secret": secret,
        "totp_uri": totp_uri,
        "is_mfa_enabled": admin.is_mfa_enabled,
        "isMfaEnabled": admin.is_mfa_enabled,
    }


@router.post("/ats-mfa/verify")
def verify_ats_admin_mfa(
    payload: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    db_company: Session = Depends(get_db_company),
    current_admin: RecruitmentAdmin = Depends(get_authenticated_admin_base),
):
    """Activate or deactivate MFA for ATS admin."""
    require_internal_secret(request)
    admin_id = payload.get("admin_id") or payload.get("adminId")
    if not admin_id and (not isinstance(current_admin, RecruitmentAdmin) or getattr(current_admin, "id", 0) == 0):
        raise HTTPException(status_code=400, detail="Admin ID wajib disertakan.")

    if not isinstance(current_admin, RecruitmentAdmin):
        admin = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == int(admin_id)).first() if admin_id else None
    else:
        admin = current_admin
    if not admin:
        raise HTTPException(status_code=404, detail="Admin tidak ditemukan.")
    require_account_identity(admin, admin_id)

    code = str(payload.get("code", "")).strip().replace(" ", "")
    enable = bool(payload.get("enable"))

    now_utc = datetime.now(timezone.utc)
    if admin.totp_locked_until:
        locked_until = admin.totp_locked_until if admin.totp_locked_until.tzinfo else admin.totp_locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now_utc:
            remaining = int((locked_until - now_utc).total_seconds())
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Akun terkunci sementara karena terlalu banyak percobaan salah. Coba lagi dalam {remaining} detik.",
            )

    if enable:
        if admin.is_mfa_enabled:
            raise HTTPException(status_code=400, detail="MFA sudah aktif.")
        if not admin.mfa_secret:
            raise HTTPException(status_code=400, detail="Secret MFA belum diinisialisasi.")

        current_timestep = int(time.time() / 30)
        if getattr(admin, "last_used_totp_timestep", None) == current_timestep:
            raise HTTPException(status_code=400, detail="Kode TOTP telah digunakan. Tunggu kode berikutnya (30 detik).")

        totp = pyotp.TOTP(admin.mfa_secret)
        if not totp.verify(code, valid_window=1):
            admin.totp_failed_attempts = getattr(admin, "totp_failed_attempts", 0) + 1
            if admin.totp_failed_attempts >= 5:
                admin.totp_locked_until = now_utc + timedelta(minutes=15)
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="Kode verifikasi 6-digit tidak valid atau sudah kedaluwarsa.",
            )

        admin.totp_failed_attempts = 0
        admin.totp_locked_until = None
        admin.last_used_totp_timestep = current_timestep
        admin.is_mfa_enabled = True
        admin.mfa_verified_at = now_utc
        db.commit()

        cms_user = db_company.query(User).filter(User.email == admin.email).first()
        if cms_user:
            cms_user.mfa_enabled = True
            cms_user.mfa_secret = admin.mfa_secret
            cms_user.mfa_verified_at = now_utc
            db_company.commit()

        return {
            "success": True,
            "message": "Autentikasi 2 Langkah (Google Authenticator) berhasil diaktifkan untuk akun Anda!",
        }
    else:
        admin_roles = ["admin", "hr", "user_dept", "marketing"]
        if admin.role in admin_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MFA wajib aktif untuk akun administrator dan tidak dapat dinonaktifkan.",
            )

        if not admin.mfa_secret:
            raise HTTPException(status_code=400, detail="MFA belum diaktifkan.")

        current_password = str(payload.get("current_password") or payload.get("password") or "").strip()
        pw_ok = current_password and verify_password(current_password, admin.password)
        totp = pyotp.TOTP(admin.mfa_secret)
        totp_ok = code and totp.verify(code, valid_window=1)
        if not (pw_ok or totp_ok):
            raise HTTPException(
                status_code=400,
                detail="Menonaktifkan MFA memerlukan kode verifikasi TOTP yang valid atau kata sandi akun.",
            )

        admin.is_mfa_enabled = False
        admin.mfa_verified_at = None
        db.commit()

        cms_user = db_company.query(User).filter(User.email == admin.email).first()
        if cms_user:
            cms_user.mfa_enabled = False
            cms_user.mfa_verified_at = None
            db_company.commit()

        return {"success": True, "message": "MFA successfully disabled."}

    now_utc = datetime.now(timezone.utc)
    if admin.totp_locked_until:
        locked_until = admin.totp_locked_until if admin.totp_locked_until.tzinfo else admin.totp_locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now_utc:
            remaining = int((locked_until - now_utc).total_seconds())
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Akun terkunci sementara karena terlalu banyak percobaan salah. Coba lagi dalam {remaining} detik.",
            )

    if enable:
        if admin.is_mfa_enabled:
            raise HTTPException(status_code=400, detail="MFA sudah aktif.")
        if not admin.mfa_secret:
            raise HTTPException(status_code=400, detail="Secret MFA belum diinisialisasi.")

        current_timestep = int(time.time() / 30)
        if getattr(admin, "last_used_totp_timestep", None) == current_timestep:
            raise HTTPException(status_code=400, detail="Kode TOTP telah digunakan. Tunggu kode berikutnya (30 detik).")

        totp = pyotp.TOTP(admin.mfa_secret)
        if not totp.verify(code, valid_window=1):
            admin.totp_failed_attempts = getattr(admin, "totp_failed_attempts", 0) + 1
            if admin.totp_failed_attempts >= 5:
                admin.totp_locked_until = now_utc + timedelta(minutes=15)
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="Kode verifikasi 6-digit tidak valid atau sudah kedaluwarsa.",
            )

        admin.totp_failed_attempts = 0
        admin.totp_locked_until = None
        admin.last_used_totp_timestep = current_timestep
        admin.is_mfa_enabled = True
        admin.mfa_verified_at = now_utc
        db.commit()

        cms_user = db_company.query(User).filter(User.email == admin.email).first()
        if cms_user:
            cms_user.mfa_enabled = True
            cms_user.mfa_secret = admin.mfa_secret
            cms_user.mfa_verified_at = now_utc
            db_company.commit()

        return {
            "success": True,
            "message": "Autentikasi 2 Langkah (Google Authenticator) berhasil diaktifkan untuk akun Anda!",
        }
    else:
        admin_roles = ["admin", "hr", "user_dept", "marketing"]
        if admin.role in admin_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MFA wajib aktif untuk akun administrator dan tidak dapat dinonaktifkan.",
            )

        if not admin.mfa_secret:
            raise HTTPException(status_code=400, detail="MFA belum diaktifkan.")

        current_password = str(payload.get("current_password") or payload.get("password") or "").strip()
        pw_ok = current_password and verify_password(current_password, admin.password)
        totp = pyotp.TOTP(admin.mfa_secret)
        totp_ok = code and totp.verify(code, valid_window=1)
        if not (pw_ok or totp_ok):
            raise HTTPException(
                status_code=400,
                detail="Menonaktifkan MFA memerlukan kode verifikasi TOTP yang valid atau kata sandi akun.",
            )

        admin.is_mfa_enabled = False
        admin.mfa_verified_at = None
        db.commit()

        cms_user = db_company.query(User).filter(User.email == admin.email).first()
        if cms_user:
            cms_user.mfa_enabled = False
            cms_user.mfa_verified_at = None
            db_company.commit()

        return {"success": True, "message": "MFA successfully disabled."}


