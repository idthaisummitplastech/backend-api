import json
from typing import Any, Dict
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
from app.api.deps import get_current_admin, get_current_applicant
from app.models.auth import RecruitmentAdmin, User
from app.models.recruitment import Applicant
from app.core.middleware import limiter
from app.core.security import verify_password, create_access_token
from app.core.config import settings

router = APIRouter()


@router.post("/cms-login")
@limiter.limit("15/minute")
def login_cms_user(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db_company),
):
    """CMS Admin authentication for Company Profile — hormati is_active & portal_access."""
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email dan password wajib diisi.")

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(status_code=401, detail="Email atau password salah.")

    # Toggle active — jika dinonaktifkan, tolak login di semua portal
    if hasattr(user, "is_active") and getattr(user, "is_active") is False:
        raise HTTPException(status_code=403, detail="Akun Anda dinonaktifkan oleh Administrator. Hubungi admin untuk aktivasi kembali.")

    # Portal access — cms-login hanya untuk web-perusahaan
    pa = getattr(user, "portal_access", "both") or "both"
    if pa not in ("perusahaan", "both"):
        raise HTTPException(status_code=403, detail="Akun Anda tidak memiliki akses ke Web Perusahaan. Minta admin mengaktifkan portal_access = Perusahaan atau Keduanya.")

    token = create_access_token(
        subject=str(user.id),
        role=user.role,
        department=getattr(user, "department", None),
        extra_claims={"email": user.email, "name": user.name}
    )
    has_secret = bool(user.mfa_secret)
    return {
        "success": True,
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "mfa_enabled": user.mfa_enabled,
            "has_mfa_secret": has_secret,
        },
        "requires_mfa": user.mfa_enabled,
        "has_mfa_secret": has_secret,
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
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        mfa_code = str(payload.get("mfa_code") or payload.get("mfaCode", "")).strip()

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username/Email dan password wajib diisi.")

        clean_input = username.lower()
        if clean_input.endswith("@itsp.com"):
            clean_input = clean_input.replace("@itsp.com", "@itsp.co.id")

        # 1. Check central CMS users (web_perusahaan)
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
                raise HTTPException(status_code=403, detail="Akun Anda dinonaktifkan oleh Administrator.")
            pa_cms = getattr(cms_user, "portal_access", "both") or "both"
            if pa_cms not in ("karir", "both"):
                raise HTTPException(status_code=403, detail="Akun Anda tidak memiliki akses ke Portal Karir. Minta admin set portal_access = Karir / Keduanya.")
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

            token = create_access_token(
                subject=str(admin_id),
                role=admin_role,
                department=admin_dept,
                extra_claims={"email": cms_user.email, "name": admin_name}
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
                },
            }

        # 2. Fallback to local recruitment_admins (web_karir)
        local_admin = db.query(RecruitmentAdmin).filter(
            (RecruitmentAdmin.username.ilike(clean_input)) | (RecruitmentAdmin.email.ilike(clean_input))
        ).first()

        if not local_admin:
            raise HTTPException(status_code=401, detail="Kredensial login tidak ditemukan. Periksa kembali username/email Anda.")

        if not verify_password(password, local_admin.password):
            raise HTTPException(status_code=401, detail="Password salah. Silakan coba kembali.")

        if hasattr(local_admin, "is_active") and getattr(local_admin, "is_active") is False:
            raise HTTPException(status_code=403, detail="Akun Anda dinonaktifkan oleh Administrator.")
        pa_local = getattr(local_admin, "portal_access", "both") or "both"
        if pa_local not in ("karir", "both"):
            raise HTTPException(status_code=403, detail="Akun Anda tidak memiliki akses ke Portal Karir. Minta admin set portal_access = Karir / Keduanya.")

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

        token = create_access_token(
            subject=str(local_admin.id),
            role=local_admin.role,
            department=local_admin.department,
            extra_claims={"email": local_admin.email, "name": local_admin.name}
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
    """Admin & Evaluator authentication with rate-limiting and 2FA support."""
    return auth_service.authenticate_admin(
        db,
        username_or_email=payload.username_or_email,
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
    return ApiResponse(data=success, message="MFA 2-Faktor berhasil diaktifkan.")


# --- CMS ADMIN MFA ENDPOINTS (Company Profile) ---
@router.get("/cms-mfa/{user_id}")
def get_cms_user_mfa(
    user_id: int,
    db: Session = Depends(get_db_company),
):
    """Retrieve CMS user MFA configuration."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "mfa_enabled": user.mfa_enabled,
        "mfa_secret": user.mfa_secret,
        "backup_codes": user.backup_codes,
    }


@router.put("/cms-mfa/{user_id}/save-secret")
def save_cms_mfa_secret(
    user_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db_company),
):
    """Save generated MFA secret for CMS user before activation."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")
    secret = payload.get("secret")
    if secret:
        user.mfa_secret = secret
        db.commit()
    return {"success": True, "secret": user.mfa_secret}


@router.post("/cms-mfa/activate")
def activate_cms_mfa(
    payload: Dict[str, Any],
    db: Session = Depends(get_db_company),
):
    """Activate MFA for CMS user after code verification."""
    user_id = payload.get("user_id") or payload.get("userId")
    secret = payload.get("secret")
    backup_codes = payload.get("backup_codes") or payload.get("backupCodes")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan.")

    user.mfa_enabled = True
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
    db: Session = Depends(get_db_company),
):
    """Verify MFA code or backup code for CMS user login."""
    user_id = payload.get("user_id") or payload.get("userId")
    code = str(payload.get("code", "")).strip().replace(" ", "")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.mfa_secret:
        raise HTTPException(status_code=400, detail="Konfigurasi MFA pengguna tidak valid.")

    totp = pyotp.TOTP(user.mfa_secret)
    # Mengizinkan toleransi perbedaan waktu hingga ±15 menit (30 step x 30 detik)
    # untuk mengatasi clock drift antara jam HP dan laptop/server.
    is_valid = totp.verify(code, valid_window=30)
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
        raise HTTPException(status_code=400, detail="Kode autentikasi salah atau sudah kedaluwarsa.")

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
    db: Session = Depends(get_db),
    db_company: Session = Depends(get_db_company),
):
    """Retrieve or initialize MFA TOTP secret for ATS Admin."""
    admin = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin rekrutmen tidak ditemukan.")

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
    db: Session = Depends(get_db),
    db_company: Session = Depends(get_db_company),
):
    """Activate or deactivate MFA for ATS admin."""
    admin_id = payload.get("admin_id") or payload.get("adminId")
    code = str(payload.get("code", "")).strip().replace(" ", "")
    enable = bool(payload.get("enable"))

    admin = db.query(RecruitmentAdmin).filter(RecruitmentAdmin.id == int(admin_id)).first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin tidak ditemukan.")

    if enable:
        if not admin.mfa_secret:
            raise HTTPException(status_code=400, detail="Secret MFA belum diinisialisasi.")

        totp = pyotp.TOTP(admin.mfa_secret)
        if not totp.verify(code, valid_window=30):
            raise HTTPException(
                status_code=400,
                detail="Kode verifikasi 6-digit tidak valid atau sudah kedaluwarsa. Pastikan jam HP dan laptop/server sudah sinkron (WIB UTC+7).",
            )

        admin.is_mfa_enabled = True
        db.commit()

        cms_user = db_company.query(User).filter(User.email == admin.email).first()
        if cms_user:
            cms_user.mfa_enabled = True
            cms_user.mfa_secret = admin.mfa_secret
            db_company.commit()

        return {
            "success": True,
            "message": "Autentikasi 2 Langkah (Google Authenticator) berhasil diaktifkan untuk akun Anda!",
        }
    else:
        admin.is_mfa_enabled = False
        db.commit()

        cms_user = db_company.query(User).filter(User.email == admin.email).first()
        if cms_user:
            cms_user.mfa_enabled = False
            db_company.commit()

        return {"success": True, "message": "MFA berhasil dinonaktifkan."}


